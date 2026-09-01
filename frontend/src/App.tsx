import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
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
import { Catalog } from "@/pages/Catalog";
import { Dashboard } from "@/pages/Dashboard";
import { Generate } from "@/pages/Generate";
import { JobDetail } from "@/pages/JobDetail";
import { Login } from "@/pages/Login";
import { Onboarding } from "@/pages/Onboarding";
import { ExpressOnboarding } from "@/pages/ExpressOnboarding";
import { Growth } from "@/pages/Growth";
import { ProfileEdit } from "@/pages/ProfileEdit";
import { Rankings } from "@/pages/Rankings";
import { Postings } from "@/pages/Postings";
import { Explore } from "@/pages/Explore";
import { Assessment } from "@/pages/Assessment";
import { Register } from "@/pages/Register";
import { Universities } from "@/pages/Universities";
import { UniversityDetail } from "@/pages/UniversityDetail";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/onboarding/express" element={<ExpressOnboarding />} />
          <Route path="/catalog" element={<Catalog />} />
          <Route path="/jobs/:code" element={<JobDetail />} />
          <Route path="/generate" element={<Generate />} />
          <Route path="/rankings" element={<Rankings />} />
          <Route path="/postings" element={<Postings />} />
          <Route path="/explore" element={<Explore />} />
          <Route path="/growth" element={<Growth />} />
          <Route path="/assessment" element={<Assessment />} />
          <Route path="/universities" element={<Universities />} />
          <Route path="/universities/:id" element={<UniversityDetail />} />
          <Route path="/profile" element={<ProfileEdit />} />
          <Route path="/experience" element={<Experience />} />
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
