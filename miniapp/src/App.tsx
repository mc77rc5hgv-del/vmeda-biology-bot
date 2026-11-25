import { paidSubjectTitles, subscriptionPath } from "./lib/subscriptions";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { SubjectTheme } from "./components/SubjectTheme";
import { useEffect } from "react";
import { applyPreferredTheme } from "./lib/theme";
import { useAuthStore } from "./lib/store";
import { saveLearningNavigation } from "./lib/apiClient";
import { useQueryClient } from "@tanstack/react-query";
import { useLastStepStore } from "./lib/lastStep";
import { BottomNav } from "./components/BottomNav";
import { ExamAccessGate, type ExamScope } from "./components/ExamAccessGate";
import { HomePage } from "./pages/Home";
import { SubjectPage } from "./pages/Subject";
import { SectionPage } from "./pages/Section";
import { GroupPage } from "./pages/Group";
import { MaterialPage } from "./pages/Material";
import { TestPage } from "./pages/Test";
import { AiPage } from "./pages/Ai";
import { SubscriptionsPage } from "./pages/Subscriptions";
import { ProfilePage } from "./pages/Profile";
import { ReferralPage } from "./pages/Referral";
import { FavoritesPage } from "./pages/Favorites";
import { ProgressPage } from "./pages/Progress";
import { SearchPage } from "./pages/Search";
import { NotFoundPage } from "./pages/NotFound";
import { HistologyCatalogPage, HistologyExamPage, HistologyGuessPage } from "./pages/HistologyExam";
import { HistologyTestPage, HistologyTheoryPage } from "./pages/HistologyStudy";
import { HistologySpecimenPage } from "./pages/HistologySpecimen";

function examScopeForPath(pathname: string): ExamScope | undefined {
  if (/^\/tests\/anatomy\/?$/.test(pathname)) return "anatomy_tests";
  if (/^\/(?:histology|subjects\/histology|materials\/histology)(?:\/|$)/.test(pathname)) return "histology";
}

export function App() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const examScope = examScopeForPath(pathname);
  useEffect(() => {
    const handle = (event: Event) => {
      const subjectId = (event as CustomEvent<{subjectId: string}>).detail?.subjectId;
      // Ignore late failures from requests belonging to a page already left.
      const currentSubject = pathname.match(/^\/(?:subjects|materials|tests)\/([^/]+)/)?.[1]
        ?? (pathname.startsWith("/histology/") ? "histology" : undefined);
      if (subjectId && Object.hasOwn(paidSubjectTitles, subjectId) && currentSubject === subjectId) {
        if (examScope) {
          void queryClient.invalidateQueries({ queryKey: ["access", examScope] });
          return;
        }
        navigate(subscriptionPath(subjectId, pathname), {replace: true});
      }
    };
    window.addEventListener("vmeda:subscription-required", handle);
    return () => window.removeEventListener("vmeda:subscription-required", handle);
  }, [pathname, navigate, examScope, queryClient]);
  const owner = useAuthStore((state) => String(state.profile?.userId ?? "preview"));
  const remember = useLastStepStore((state) => state.remember);
  useEffect(() => {
    remember(owner, pathname);
    const step = useLastStepStore.getState().steps[owner];
    if (owner !== "preview" && step?.path === pathname) {
      void saveLearningNavigation(pathname).then(() => {
        void queryClient.invalidateQueries({queryKey: ["learning"]});
      }).catch(() => { /* local dated bookmark remains on network failure */ });
    }
  }, [owner, pathname, remember, queryClient]);
  const subjectId = pathname.match(/^\/(?:subjects|materials|tests)\/([^/]+)/)?.[1]
    ?? (pathname.startsWith("/histology/") ? "histology" : undefined);
  useEffect(() => { applyPreferredTheme(); }, [subjectId]);
  return (
    <>
      <SubjectTheme subjectId={subjectId} appShell>
      <ExamAccessGate scope={examScope}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/subjects/:subjectId" element={<SubjectPage />} />
        <Route path="/subjects/:subjectId/sections/:sectionId" element={<SectionPage />} />
        <Route path="/subjects/:subjectId/sections/:sectionId/groups/:groupId" element={<GroupPage />} />
        <Route path="/materials/:subjectId/:sectionId/:materialId" element={<MaterialPage />} />
        <Route path="/tests/:subjectId" element={<TestPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/histology/exam" element={<HistologyExamPage />} />
        <Route path="/histology/exam/specimens" element={<HistologyCatalogPage key="exam" />} />
        <Route path="/histology/exam/tests/:questionId?" element={<HistologyTestPage />} />
        <Route path="/histology/exam/theory/:number?" element={<HistologyTheoryPage />} />
        <Route path="/histology/exam/guess" element={<HistologyGuessPage />} />
        <Route path="/histology/diagnostics" element={<HistologyCatalogPage key="diagnostics" diagnostics />} />
        <Route path="/histology/diagnostics/:diagnosticId/guess" element={<HistologyGuessPage />} />
        <Route path="/histology/specimens/:specimenId" element={<HistologySpecimenPage />} />
        <Route path="/ai" element={<AiPage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/profile/subscriptions" element={<SubscriptionsPage />} />
        <Route path="/profile/referrals" element={<ReferralPage />} />
        <Route path="/profile/favorites" element={<FavoritesPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      </ExamAccessGate>
      <BottomNav />
      </SubjectTheme>
    </>
  );
}
