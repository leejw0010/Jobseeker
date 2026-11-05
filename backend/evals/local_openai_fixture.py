"""Synthetic loopback OpenAI protocol fixture. Never forwards requests anywhere.

Run only via playwright.local-ai.config.ts. This checks integration, not model quality.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

COUNTS = {"coach": 0, "debrief": 0, "generate": 0}
LOCK = Lock()


def reply(payload):
    try:
        data = json.loads(payload["messages"][-1]["content"])
    except (ValueError, KeyError):
        data = None
    if isinstance(data, dict) and "answer" in data:
        kind = "coach"
        quote = data["answer"][:100]
        source = next(iter(data.get("context", {}).get("essays", [])), {})
        source_fields = {"source_quote": source.get("content", "")[:100], "source_version_id": source.get("version_id")}
        result = {
            "summary": "합성 응답: 답변에 나온 선택과 확인 과정을 구분해 살펴보세요.",
            "next_action": "실제로 결과를 확인한 방법을 한 문장으로 덧붙이기",
            "criteria": [
                {"key": "specificity", "label": "구체성", "status": "보완", "reason": "결과를 확인한 방법을 설명하는 연습입니다.", "answer_quote": quote},
                {"key": "relevance", "label": "질문 적합성", "status": "충분", "reason": "질문에서 요청한 선택을 답변에 언급했습니다.", "answer_quote": quote},
                {"key": "consistency", "label": "제출본 연결", "status": "판단유보", "reason": "동일한 경험인지 직접 확인해 주세요.", "answer_quote": quote, **source_fields},
            ],
            "followup": {"text": "그 선택의 결과를 어떤 방법으로 확인했나요?", "focus": "specificity", "reason": "답변에서 언급한 선택의 확인 과정", "answer_quote": quote},
            "competency_evidence": {"observations": [{"competency_key": "problem_solving", "basis": "past_action", "quote": quote, "reason": "합성 답변에 명시된 문제 분석 행동"}]},
        }
    elif isinstance(data, dict) and "answers" in data:
        kind = "debrief"
        first = next(a for a in data["answers"] if a["transcript"] != "(전사문 없음)")
        result = {"lesson": "합성 디브리프: 선택과 결과 확인을 연결해 설명하기", "next_action": "확인한 사실 안에서 결과 검증 과정을 덧붙이기",
                  "moments": [{"order_no": first["order_no"], "quote": first["transcript"][:100], "why": "답변에 남은 실제 표현을 다시 검토하기"}]}
    else:
        kind = "generate"
        result = {"questions": [{"category": "직무", "text": "합성 프로젝트에서 문제를 분석하고 선택한 방법을 설명해 주세요.", "question_type": "project_deep_dive", "competency_keys": ["problem_solving"]}]}
    with LOCK:
        COUNTS[kind] += 1
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Request bodies and authorization headers never enter logs.

    def send_json(self, body, status=200):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self.send_json({"synthetic_fixture": True})
        elif self.path == "/counts":
            with LOCK:
                self.send_json(dict(COUNTS))
        else:
            self.send_json({"error": "unsupported local fixture route"}, 404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_json({"error": "unsupported local fixture route"}, 404)
            return
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            self.send_json(reply(data))
        except (ValueError, KeyError, TypeError, StopIteration):
            self.send_json({"error": "invalid synthetic fixture input"}, 400)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
