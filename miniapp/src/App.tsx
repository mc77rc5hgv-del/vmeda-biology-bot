import { Route, Routes } from "react-router-dom";
import { BottomNav } from "./components/BottomNav";
import { HomePage } from "./pages/Home";
import { SubjectPage } from "./pages/Subject";
import { SectionPage } from "./pages/Section";
import { GroupPage } from "./pages/Group";
import { MaterialPage } from "./pages/Material";
import { TestPage } from "./pages/Test";
import { AiPage } from "./pages/Ai";
import { ProfilePage } from "./pages/Profile";
import { ProgressPage } from "./pages/Progress";
import { NotFoundPage } from "./pages/NotFound";

export function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/subjects/:subjectId" element={<SubjectPage />} />
        <Route path="/subjects/:subjectId/sections/:sectionId" element={<SectionPage />} />
        <Route path="/subjects/:subjectId/sections/:sectionId/groups/:groupId" element={<GroupPage />} />
        <Route path="/materials/:subjectId/:sectionId/:materialId" element={<MaterialPage />} />
        <Route path="/tests/:subjectId" element={<TestPage />} />
        <Route path="/ai" element={<AiPage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      <BottomNav />
    </>
  );
}
