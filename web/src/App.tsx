import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "./api";
import { serviceNotice } from "./sttText";
import type { Health } from "./types";
import PracticeHome from "./pages/PracticeHome";
import SessionRunner from "./pages/SessionRunner";
import SessionReview from "./pages/SessionReview";
import SessionList from "./pages/SessionList";
import PracticeSettings from "./pages/PracticeSettings";
import TrackList from "./pages/TrackList";
import ApplicationPage from "./pages/ApplicationPage";
import StatsPage from "./pages/StatsPage";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setDown(true));
  }, []);
  // 음성 전사(로컬·OpenAI·꺼짐)와 AI 코칭(OpenAI 키)은 따로 켜지고 꺼진다
  const notice = health && serviceNotice(health);

  return (
    <div className="layout">
      <nav className="nav">
        <div className="brand">JobSeeker</div>
        <div className="group">② Practice</div>
        <NavLink to="/practice" end>연습 시작</NavLink>
        <NavLink to="/practice/history">연습 기록</NavLink>
        <NavLink to="/practice/settings">녹음·개인정보</NavLink>
        <div className="group">③ Track</div>
        <NavLink to="/track" end>지원 관리</NavLink>
        <NavLink to="/track/stats">통계</NavLink>
      </nav>
      <main className="main">
        {down && <div className="card err">백엔드 서버에 연결할 수 없습니다. backend 폴더에서 서버를 실행했는지 확인하세요.</div>}
        {notice && <div className="card small muted">{notice}</div>}
        <Routes>
          <Route path="/" element={<Navigate to="/practice" replace />} />
          <Route path="/practice" element={<PracticeHome />} />
          <Route path="/practice/history" element={<SessionList />} />
          <Route path="/practice/settings" element={<PracticeSettings />} />
          <Route path="/practice/sessions/:id/run" element={<SessionRunner />} />
          <Route path="/practice/sessions/:id" element={<SessionReview />} />
          <Route path="/track" element={<TrackList />} />
          <Route path="/track/stats" element={<StatsPage />} />
          <Route path="/track/:id" element={<ApplicationPage />} />
        </Routes>
      </main>
    </div>
  );
}
