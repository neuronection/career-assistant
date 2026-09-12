import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { SettingsShell } from "@/components/SettingsShell";
import { About } from "@/pages/About";
import { AIConfig } from "@/pages/settings/AIConfig";
import { AIAudit } from "@/pages/settings/AIAudit";
import { Taxonomy } from "@/pages/settings/Taxonomy";
import { Users } from "@/pages/settings/Users";
import { SchedulerSettings } from "@/pages/settings/SchedulerSettings";
import { Notifications } from "@/pages/settings/Notifications";
import { Experience } from "@/pages/Experience";
import { Education } from "@/pages/Education";
import { CvStudio } from "@/pages/CvStudio";
import { CvSynthLibrary } from "@/pages/CvSynthLibrary";
import { CvBuilder } from "@/pages/CvBuilder";
import { CvTemplateEditor } from "@/pages/CvTemplateEditor";
import { Catalog } from "@/pages/Catalog";
import { CatalogGraph } from "@/components/catalog/CatalogGraph";
import { CatalogTree } from "@/components/catalog/CatalogTree";
import { Dashboard } from "@/pages/Dashboard";
import { ChatPage } from "@/pages/ChatPage";
import { Generate } from "@/pages/Generate";
import { JobDetail } from "@/pages/JobDetail";
import { Onboarding } from "@/pages/Onboarding";
import { ExpressOnboarding } from "@/pages/ExpressOnboarding";
import { Growth } from "@/pages/Growth";
import { Interviews } from "@/pages/Interviews";
import { ProfileEdit } from "@/pages/ProfileEdit";
import { ProfileImport } from "@/pages/ProfileImport";
import { Rankings } from "@/pages/Rankings";
import { Compare } from "@/pages/Compare";
import { Postings } from "@/pages/Postings";
import { PostingsFeed } from "@/components/postings/PostingsFeed";
import { Explore } from "@/pages/Explore";
import { Autopilot } from "@/pages/Autopilot";
import { Assessment } from "@/pages/Assessment";
import { Universities } from "@/pages/Universities";
import { UniversityDetail } from "@/pages/UniversityDetail";

function UniversityRedirect() {
  const { id } = useParams();
  return <Navigate to={`/catalog/universities/${id}`} replace />;
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/onboarding/express" element={<ExpressOnboarding />} />
          <Route path="/catalog" element={<Catalog />}>
            <Route index element={<CatalogTree />} />
            <Route path="graph" element={<CatalogGraph />} />
            <Route path="generate" element={<Generate />} />
          </Route>
          <Route path="/jobs/:code" element={<JobDetail />} />
          <Route path="/generate" element={<Navigate to="/catalog/generate" replace />} />
          <Route path="/rankings" element={<Rankings />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/postings" element={<Postings />}>
            <Route index element={<PostingsFeed />} />
            <Route path="search" element={<Explore />} />
          </Route>
          <Route path="/explore" element={<Navigate to="/postings/search" replace />} />
          <Route path="/autopilot" element={<Autopilot />} />
          <Route path="/interviews" element={<Interviews />} />
          <Route path="/growth" element={<Growth />} />
          <Route path="/profile" element={<ProfileEdit />} />
          <Route path="/profile/import" element={<ProfileImport />} />
          <Route path="/profile/import/:documentId" element={<ProfileImport />} />
          <Route path="/profile/experience" element={<Experience />} />
          <Route path="/profile/education" element={<Education />} />
          <Route path="/profile/assessment" element={<Assessment />} />
          <Route path="/assessment" element={<Navigate to="/profile/assessment" replace />} />
          <Route path="/catalog/universities" element={<Universities />} />
          <Route path="/catalog/universities/:id" element={<UniversityDetail />} />
          <Route path="/universities" element={<Navigate to="/catalog/universities" replace />} />
          <Route path="/universities/:id" element={<UniversityRedirect />} />
          <Route path="/cv" element={<CvStudio />} />
          <Route path="/cv/synth" element={<CvSynthLibrary />} />
          <Route path="/cv/:id" element={<CvBuilder />} />
          <Route path="/cv/templates/:id" element={<CvTemplateEditor />} />
          <Route path="/about" element={<About />} />
          <Route path="/settings" element={<SettingsShell />}>
            <Route index element={<Navigate to="/settings/ai" replace />} />
            <Route path="ai" element={<AIConfig />} />
            <Route path="taxonomy" element={<Taxonomy />} />
            <Route path="users" element={<Users />} />
            <Route path="scheduler" element={<SchedulerSettings />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="audit" element={<AIAudit />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
