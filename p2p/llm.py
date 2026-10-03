"""OpenRouter chat client with hard budget enforcement and per-call tracing."""
import json
import re
import time

import requests

URL = "https://openrouter.ai/api/v1/chat/completions"


class BudgetError(RuntimeError):
    pass


class Trace:
    def __init__(self, path, t0):
        self.f = open(path, "w", encoding="utf-8")
        self.t0 = t0

    def __call__(self, stage, action, result, **kw):
        ev = {"t": round(time.time() - self.t0, 2), "stage": stage, "action": action, "result": result}
        ev.update(kw)
        self.f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


class LLM:
    def __init__(self, model, key, trace, t0, max_requests=10, max_completion=30000, deadline_s=540):
        self.model, self.key, self.trace, self.t0 = model, key, trace, t0
        self.max_requests, self.max_completion, self.deadline = max_requests, max_completion, deadline_s
        self.requests = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.cached_tokens = 0
        self.calls = []

    def remaining_completion(self):
        return self.max_completion - self.completion_tokens

    def time_left(self):
        return self.deadline - (time.time() - self.t0)

    def chat(self, stage, messages, max_tokens, temperature=0.2, retries=2, extra=None):
        last_err = None
        for attempt in range(retries + 1):
            if self.requests >= self.max_requests:
                raise BudgetError("request budget exhausted")
            mt = min(max_tokens, self.remaining_completion() - 200)
            if mt < 800:
                raise BudgetError("completion-token budget exhausted")
            tl = self.time_left()
            if tl < 20:
                raise BudgetError("time budget exhausted")
            body = {"model": self.model, "messages": messages, "max_tokens": mt, "temperature": temperature,
                    "stream": True, "usage": {"include": True}}
            if extra:
                body.update(extra)
            self.requests += 1
            t = time.time()
            try:
                r = requests.post(URL, headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                                                "X-Title": "paper-to-playground"},
                                  json=body, stream=True, timeout=(10, 90))
                if r.status_code != 200:
                    j = r.json() if r.content else {}
                else:
                    j = self._read_stream(r, deadline=time.time() + max(20, tl - 15))
                dt = round(time.time() - t, 2)
            except Exception as e:  # network error / timeout / bad JSON
                dt = round(time.time() - t, 2)
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                self.trace(stage, "llm_call", "error", request=self.requests, attempt=attempt, elapsed_s=dt, error=last_err)
                time.sleep(min(2 * (attempt + 1), 5))
                continue
            if j.get("aborted"):  # usage of a cancelled stream is not reported: estimate conservatively
                j["usage"] = j.get("usage") or {"prompt_tokens": sum(len(m["content"]) for m in messages) // 3,
                                                  "completion_tokens": len(j["choices"][0]["message"]["content"]) // 3 + 1}
            u = j.get("usage") or {}
            pt, ct = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
            rt = int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
            cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
            self.prompt_tokens += pt
            self.completion_tokens += ct
            self.reasoning_tokens += rt
            self.cached_tokens += cached
            ch = (j.get("choices") or [{}])[0]
            content = ((ch.get("message") or {}).get("content")) or ""
            finish = ch.get("finish_reason") or ch.get("native_finish_reason")
            err = j.get("error") or ch.get("error")
            rec = dict(request=self.requests, attempt=attempt, generation_id=j.get("id"), http=r.status_code,
                       stream_aborted=j.get("aborted"), usage_estimated=bool(j.get("aborted") and not j.get("usage_reported")),
                       prompt_tokens=pt, completion_tokens=ct, reasoning_tokens=rt, cached_tokens=cached,
                       elapsed_s=dt, max_tokens=mt, finish_reason=finish, output_chars=len(content))
            self.calls.append(rec)
            if r.status_code != 200 or err or not content.strip():
                last_err = f"HTTP {r.status_code}: {json.dumps(err)[:300] if err else 'empty content'}"
                self.trace(stage, "llm_call", "error", error=last_err, **rec)
                m = re.search(r"can only afford (\d+)", json.dumps(err) if err else "")
                if r.status_code == 402 and m and int(m.group(1)) >= 2500:
                    max_tokens = int(int(m.group(1)) * 0.9)  # key credit cap: retry with a smaller ceiling
                    continue
                if r.status_code in (400, 401, 402, 403, 404):
                    break
                time.sleep(min((6 if r.status_code == 429 else 2) * (attempt + 1), 15, max(0, self.time_left() - 60)))
                continue
            self.trace(stage, "llm_call", "ok", **rec)
            return content, finish
        raise RuntimeError(f"LLM call failed: {last_err}")

    @staticmethod
    def _looping(text):
        """True if the tail of the output is a short pattern repeated (degenerate generation)."""
        tail = text[-400:]
        if len(tail) < 400:
            return False
        if len(set(tail)) <= 3:
            return True
        for p in range(2, 41):
            if tail[-240:] == tail[-240 - p:-p]:
                return True
        return False

    def _read_stream(self, r, deadline):
        parts, usage, finish, gid, err, aborted, n = [], None, None, None, None, None, 0
        r.encoding = "utf-8"  # SSE responses carry no charset; requests would otherwise assume latin-1
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue  # keep-alive comments
            data = raw[5:].strip()
            if data == "[DONE]":
                break
            try:
                ch = json.loads(data)
            except ValueError:
                continue
            gid = ch.get("id") or gid
            usage = ch.get("usage") or usage
            err = ch.get("error") or err
            for c in ch.get("choices") or []:
                d = (c.get("delta") or {}).get("content")
                if d:
                    parts.append(d)
                    n += len(d)
                finish = c.get("finish_reason") or finish
            if n > 2000 and len(parts) % 25 == 0 and self._looping("".join(parts[-200:])):
                aborted = "repetition loop detected"
                break
            if time.time() > deadline:
                aborted = "time budget"
                break
        r.close()
        text = "".join(parts)
        if aborted:
            finish = "length"  # treat like truncation: unfinished last block is dropped
        return {"id": gid, "usage": usage, "usage_reported": bool(usage), "error": err, "aborted": aborted,
                "choices": [{"message": {"content": text}, "finish_reason": finish}]}

    def totals(self):
        return dict(requests=self.requests, prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens,
                    reasoning_tokens=self.reasoning_tokens, cached_tokens=self.cached_tokens,
                    total_tokens=self.prompt_tokens + self.completion_tokens)
