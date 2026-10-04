import { Route, Routes, useLocation } from "react-router-dom";
import { SubjectTheme } from "./components/SubjectTheme";
import { useEffect } from "react";
import { useAuthStore } from "./lib/store";
import { useLastStepStore } from "./lib/lastStep";
import { BottomNav } from "./components/BottomNav";
import { HomePage } from "./pages/Home";
import { SubjectPage } from "./pages/Subject";
import { SectionPage } from "./pages/Section";
import { GroupPage } from "./pages/Group";
import { MaterialPage } from "./pages/Material";
import { TestPage } from "./pages/Test";
import { AiPage } from "./pages/Ai";
import { ProfilePage } from "./pages/Profile";
import { ReferralPage } from "./pages/Referral";
import { FavoritesPage } from "./pages/Favorites";
import { ProgressPage } from "./pages/Progress";
import { NotFoundPage } from "./pages/NotFound";
import { HistologyExamPage } from "./pages/HistologyExam";
import { HistologySpecimenPage } from "./pages/HistologySpecimen";

export function App() {
  const { pathname } = useLocation();
  const owner = useAuthStore((state) => String(state.profile?.userId ?? "preview"));
  const remember = useLastStepStore((state) => state.remember);
  useEffect(() => { remember(owner, pathname); }, [owner, pathname, remember]);
  const subjectId = pathname.match(/^\/(?:subjects|materials|tests)\/([^/]+)/)?.[1]
    ?? (pathname.startsWith("/histology/") ? "histology" : undefined);
  return (
    <>
      <SubjectTheme subjectId={subjectId}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/subjects/:subjectId" element={<SubjectPage />} />
        <Route path="/subjects/:subjectId/sections/:sectionId" element={<SectionPage />} />
        <Route path="/subjects/:subjectId/sections/:sectionId/groups/:groupId" element={<GroupPage />} />
        <Route path="/materials/:subjectId/:sectionId/:materialId" element={<MaterialPage />} />
        <Route path="/tests/:subjectId" element={<TestPage />} />
        <Route path="/histology/exam" element={<HistologyExamPage />} />
        <Route path="/histology/specimens/:specimenId" element={<HistologySpecimenPage />} />
        <Route path="/ai" element={<AiPage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/profile/referrals" element={<ReferralPage />} />
        <Route path="/profile/favorites" element={<FavoritesPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      <BottomNav />
      </SubjectTheme>
    </>
  );
}
