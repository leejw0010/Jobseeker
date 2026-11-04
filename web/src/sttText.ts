import type { Health, SttStatus } from "./types";

/** 음성 전사를 위해 원본 녹음이 어디로 가는지(동의·설정 화면). 서버 상태를 아직 모르면 두 경우를 다 알린다 */
export function sttDestination(stt: SttStatus | null | undefined): string {
  if (!stt) return "음성 전사는 서버 설정을 따라요. 로컬 전사면 원본 녹음을 외부로 보내지 않고, OpenAI 전사면 원본 녹음을 OpenAI로 보내요.";
  if (stt.provider === "local") return "음성 전사는 JobSeeker 서버 안에서 직접 해요(로컬 Whisper 모델). 원본 녹음을 외부 서비스로 보내지 않아요.";
  if (stt.provider === "openai") return "음성 전사에는 OpenAI 음성 인식을 써요. OpenAI 키가 설정된 경우 원본 녹음을 OpenAI로 보내요.";
  return "자동 음성 전사는 꺼져 있어요. 원본 녹음은 저장만 하고 어디에도 보내지 않아요.";
}

/** 상단 안내. 음성 전사와 AI 코칭의 상태를 따로 알린다. 둘 다 쓸 수 있으면 null */
export function serviceNotice({ stt, openai }: Pick<Health, "stt" | "openai">): string | null {
  const sttError = stt.available && stt.state === "error";
  if (stt.available && !sttError && openai) return null;
  if (!stt.available && !openai) return "현재 자동 음성 전사와 AI 코칭은 연결되어 있지 않아요. 녹음·글 답변·기본 점검은 사용할 수 있어요.";
  const speech = sttError
    ? `음성 전사: 로컬 음성 인식 모델을 쓸 수 없어요(${stt.error}). 녹음은 보관해 두니 나중에 다시 시도할 수 있어요.`
    : !stt.available
      ? "음성 전사: 연결되어 있지 않아요. 녹음은 저장되고 전사문은 직접 입력할 수 있어요."
      : stt.provider === "local"
        ? `음성 전사: 이 서버에서 직접 해요(로컬 Whisper${stt.model ? ` ${stt.model}` : ""}, 외부로 보내지 않음).`
        : "음성 전사: OpenAI 음성 인식을 써요.";
  const coaching = openai ? "AI 코칭: 연결됨." : "AI 코칭: 연결되어 있지 않아 기본 점검으로 대신해요.";
  return `${speech} ${coaching}`;
}
