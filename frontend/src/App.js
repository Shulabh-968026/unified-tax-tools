import "@/App.css";
import "@/index.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider } from "@/lib/auth";
import { Toaster } from "@/components/ui/sonner";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
import ProtectedRoute from "@/pages/ProtectedRoute";
import ClientList from "@/pages/ClientList";
import ClientUtilities from "@/pages/ClientUtilities";
import ClientHome from "@/pages/ClientHome";
import { MappingDashboard, ReportDashboard } from "@/pages/Dashboard";
import Consolidated from "@/pages/Consolidated";
import AdminUsers from "@/pages/AdminUsers";
import Msme43bhLanding from "@/pages/msme43bh/Landing";
import Msme43bhSessionDashboard from "@/pages/msme43bh/SessionDashboard";
import GstReconLanding from "@/pages/gst_recon/Landing";
import BcLanding from "@/pages/balance_confirmation/Landing";

function AppRouter() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback/>;
  }

  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace/>}/>
      <Route path="/login" element={<Login/>}/>
      <Route path="/dashboard" element={<ProtectedRoute><ClientList/></ProtectedRoute>}/>
      <Route path="/dashboard/admin" element={<ProtectedRoute><AdminUsers/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId" element={<ProtectedRoute><ClientUtilities/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/clause-44" element={<ProtectedRoute><ClientHome/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/clause-44/consolidated/:period" element={<ProtectedRoute><Consolidated/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/msme-43bh" element={<ProtectedRoute><Msme43bhLanding/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/msme-43bh/sessions/:sid" element={<ProtectedRoute><Msme43bhSessionDashboard/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/gst-recon" element={<ProtectedRoute><GstReconLanding/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/balance-confirmation" element={<ProtectedRoute><BcLanding/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/balance-confirmation/runs/:rid" element={<ProtectedRoute><BcLanding/></ProtectedRoute>}/>
      <Route path="/dashboard/runs/:runId" element={<ProtectedRoute><MappingDashboard/></ProtectedRoute>}/>
      <Route path="/dashboard/runs/:runId/report" element={<ProtectedRoute><ReportDashboard/></ProtectedRoute>}/>
      <Route path="*" element={<Navigate to="/dashboard" replace/>}/>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRouter/>
        <Toaster position="top-right" richColors closeButton />
      </AuthProvider>
    </BrowserRouter>
  );
}
