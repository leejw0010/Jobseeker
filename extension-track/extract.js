// 채용 공고 페이지에서 회사·직무를 추정한다. 사이트마다 구조가 달라 완벽하지 않으므로
// 팝업에서 사용자가 확인·수정한 뒤 저장한다.

/** 페이지 안에서 실행된다(chrome.scripting.executeScript). 외부 변수를 쓰면 안 된다. */
export function readPage() {
  const meta = (sel) => document.querySelector(sel)?.getAttribute("content")?.trim() || "";
  return {
    url: location.href,
    title: document.title || "",
    ogTitle: meta('meta[property="og:title"]'),
    siteName: meta('meta[property="og:site_name"]'),
    h1: document.querySelector("h1")?.innerText?.trim().slice(0, 200) || "",
  };
}

// 채용 플랫폼 이름(제목 끝에 붙는 경우가 많아 떼어 낸다)
const PLATFORMS = ["사람인", "잡코리아", "원티드", "wanted", "리멤버", "점핏", "jumpit", "로켓펀치", "linkedin", "잡플래닛", "인크루트", "프로그래머스", "캐치", "링커리어"];
const isPlatform = (s) => PLATFORMS.some((p) => s.toLowerCase().includes(p.toLowerCase()));

const JOB_RULES = [
  ["데이터", /데이터|data|분석|analyst|머신러닝|machine learning|\bml\b|\bai\b|인공지능/i],
  ["개발", /개발|developer|engineer|엔지니어|백엔드|backend|프론트|frontend|서버|server|ios|android|devops|sre|풀스택/i],
  ["디자인", /디자인|디자이너|designer|\bux\b|\bui\b|bx/i],
  ["기획", /기획|\bpm\b|\bpo\b|product manager|프로덕트|서비스 기획|사업개발/i],
  ["마케팅", /마케팅|마케터|marketing|growth|브랜드|퍼포먼스|콘텐츠/i],
];

export function guessJobCategory(text) {
  for (const [cat, re] of JOB_RULES) if (re.test(text)) return cat;
  return "기타";
}

/** readPage() 결과로 회사·직무·직무 분류를 추정한다. */
export function guessPosting(page) {
  const raw = (page.ogTitle || page.title || "").replace(/\s+/g, " ").trim();
  let company = "";
  let position = "";

  // "[회사명] 공고 제목" 형식
  const bracket = raw.match(/^\s*[[(【]([^\])】]+)[\])】]\s*(.+)$/);
  let rest = raw;
  if (bracket) {
    company = bracket[1].trim();
    rest = bracket[2];
  }
  // "제목 | 회사 - 플랫폼" 같은 구분자 분리 후 플랫폼 이름 제거
  const parts = rest.split(/\s+[|│·\-–—]\s+|\s*\|\s*/).map((s) => s.trim()).filter(Boolean).filter((s) => !isPlatform(s));
  if (!company) {
    if (parts.length >= 2) {
      position = parts[0];
      company = parts[1];
    } else {
      position = parts[0] || page.h1 || "";
    }
  } else {
    position = parts[0] || page.h1 || "";
  }
  if (!company && page.siteName && !isPlatform(page.siteName)) company = page.siteName;
  if (!company) {
    try {
      const host = new URL(page.url).hostname.replace(/^www\.|^careers?\.|^recruit\.|^jobs?\./, "");
      if (!isPlatform(host)) company = host.split(".")[0];
    } catch {
      /* URL 아님 */
    }
  }
  // "백엔드 개발자 채용", "채용 공고" 같은 꼬리말을 떼고, 남는 게 없으면 본문 제목(h1)을 쓴다
  const clean = (t) => t.replace(/(\s*(채용\s*공고|채용|모집|공고|recruit(ing|ment)?|hiring))+\s*$/i, "").trim();
  position = clean(position) || clean(page.h1 || "");
  return {
    company: company.slice(0, 100),
    position: position.slice(0, 100),
    job_category: guessJobCategory(`${position} ${page.h1}`),
    url: page.url,
  };
}
