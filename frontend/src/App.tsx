import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { SessionGate } from "@/components/SessionGate";
import { SettingsShell } from "@/components/SettingsShell";
import { About } from "@/pages/About";
import { Account } from "@/pages/settings/Account";
import { AIConfig } from "@/pages/settings/AIConfig";
import { JobRadarSettings } from "@/pages/settings/JobRadar";
import { AIAudit } from "@/pages/settings/AIAudit";
import { Taxonomy } from "@/pages/settings/Taxonomy";
import { CompanyRules } from "@/pages/settings/CompanyRules";
import { ToolsConfig } from "@/pages/settings/ToolsConfig";
import { Users } from "@/pages/settings/Users";
import { SchedulerSettings } from "@/pages/settings/SchedulerSettings";
import { Notifications } from "@/pages/settings/Notifications";
import { Experience } from "@/features/profile/pages/Experience";
import { Education } from "@/features/profile/pages/Education";
import { CvStudio } from "@/features/cv/pages/CvStudio";
import { CvSynthLibrary } from "@/features/cv/pages/CvSynthLibrary";
import { CvBuilder } from "@/features/cv/pages/CvBuilder";
import { CvTemplateEditor } from "@/features/cv/pages/CvTemplateEditor";
import { Catalog } from "@/features/catalog/pages/Catalog";
import { CatalogGraph } from "@/features/catalog/components/catalog/CatalogGraph";
import { CatalogTree } from "@/features/catalog/components/catalog/CatalogTree";
import { Dashboard } from "@/features/profile/pages/Dashboard";
import { Applications } from "@/features/postings/pages/Applications";
import { ChatPage } from "@/features/chat/pages/ChatPage";
import { Generate } from "@/features/catalog/pages/Generate";
import { JobDetail } from "@/features/catalog/pages/JobDetail";
import { Onboarding } from "@/features/profile/pages/Onboarding";
import { OnboardingSetup } from "@/pages/OnboardingSetup";
import { ExpressOnboarding } from "@/features/profile/pages/ExpressOnboarding";
import { ExtensionSurfacePage } from "@/features/integrations/pages/ExtensionSurface";
import { SourceDetailPage } from "@/features/integrations/pages/SourceDetail";
import { Growth } from "@/features/growth/pages/Growth";
import { Interviews } from "@/features/interviews/pages/Interviews";
import { PathExplorer } from "@/features/paths/pages/PathExplorer";
import { ProfileEdit } from "@/features/profile/pages/ProfileEdit";
import { ProfileImport } from "@/features/profile/pages/ProfileImport";
import { Rankings } from "@/features/catalog/pages/Rankings";
import { Compare } from "@/features/catalog/pages/Compare";
import { Postings } from "@/features/postings/pages/Postings";
import { PostingDetailPage } from "@/features/postings/pages/PostingDetailPage";
import { PostingsFeed } from "@/features/postings/components/postings/PostingsFeed";
import { Explore } from "@/features/catalog/pages/Explore";
import { Autopilot } from "@/features/growth/pages/Autopilot";
import { Assessment } from "@/features/assessment/pages/Assessment";
import { Universities } from "@/features/university/pages/Universities";
import { UniversityDetail } from "@/features/university/pages/UniversityDetail";
import { Companies } from "@/features/companies/pages/Companies";
import { CompanyDetail } from "@/features/companies/pages/CompanyDetail";
import { SkillPage } from "@/features/skills/pages/SkillPage";

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
            <SessionGate>
              <Layout />
            </SessionGate>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/onboarding/setup" element={<OnboardingSetup />} />
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
            <Route index element={<Navigate to="/postings/search" replace />} />
            <Route path="feed" element={<PostingsFeed />} />
            <Route path="search" element={<Explore />} />
          </Route>
          <Route path="/postings/:ref" element={<PostingDetailPage />} />
          <Route path="/applications" element={<Applications />} />
          <Route path="/explore" element={<Navigate to="/postings/search" replace />} />
          <Route path="/autopilot" element={<Autopilot />} />
          <Route path="/interviews" element={<Interviews />} />
          <Route path="/growth" element={<Growth />} />
          <Route path="/paths" element={<PathExplorer />} />
          <Route path="/extensions/:extensionId" element={<ExtensionSurfacePage />} />
          <Route path="/sources/:sourceId" element={<SourceDetailPage />} />
          <Route path="/profile" element={<ProfileEdit />} />
          <Route path="/profile/import" element={<ProfileImport />} />
          <Route path="/profile/import/:documentId" element={<ProfileImport />} />
          <Route path="/profile/experience" element={<Experience />} />
          <Route path="/profile/education" element={<Education />} />
          <Route path="/profile/assessment" element={<Assessment />} />
          <Route path="/assessment" element={<Navigate to="/profile/assessment" replace />} />
          <Route path="/companies" element={<Companies />} />
          <Route path="/companies/:key" element={<CompanyDetail />} />
          <Route path="/skills/:key" element={<SkillPage />} />
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
            <Route index element={<Navigate to="/settings/account" replace />} />
            <Route path="account" element={<Account />} />
            <Route path="radar" element={<JobRadarSettings />} />
            <Route path="ai" element={<AIConfig />} />
            <Route path="tools" element={<ToolsConfig />} />
            <Route path="taxonomy" element={<Taxonomy />} />
            <Route path="companies" element={<CompanyRules />} />
            <Route path="users" element={<Users />} />
            <Route path="automations" element={<SchedulerSettings />} />
            {/* Legacy deep links (ADR-0033 INV-6): scheduler → automations */}
            <Route path="scheduler" element={<Navigate to="/settings/automations" replace />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="audit" element={<AIAudit />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
