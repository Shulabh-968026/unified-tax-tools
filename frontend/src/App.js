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
import Clause44Run from "@/pages/clause44/Clause44Run";
import Consolidated from "@/pages/Consolidated";
import AdminUsers from "@/pages/AdminUsers";
import Msme43bhLanding from "@/pages/msme43bh/Landing";
import Msme43bhSessionDashboard from "@/pages/msme43bh/SessionDashboard";
import GstReconLanding from "@/pages/gst_recon/Landing";
import BcLanding from "@/pages/balance_confirmation/Landing";
import BcConfirmPage from "@/pages/balance_confirmation/ConfirmPage";
import FixedAssetsLanding from "@/pages/fixed_assets/Landing";
import FsDesignerLanding from "@/pages/fin_statement/Landing";
import FsRunPage from "@/pages/fin_statement/RunPage";

function AppRouter() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback/>;
  }

  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace/>}/>
      <Route path="/login" element={<Login/>}/>
      <Route path="/confirm/:token" element={<BcConfirmPage/>}/>
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
      <Route path="/dashboard/clients/:clientId/utilities/fixed-assets" element={<ProtectedRoute><FixedAssetsLanding/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/fixed-assets/runs/:rid" element={<ProtectedRoute><FixedAssetsLanding/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/fin-statement" element={<ProtectedRoute><FsDesignerLanding/></ProtectedRoute>}/>
      <Route path="/dashboard/clients/:clientId/utilities/fin-statement/runs/:rid" element={<ProtectedRoute><FsRunPage/></ProtectedRoute>}/>
      <Route path="/dashboard/runs/:runId" element={<ProtectedRoute><Clause44Run/></ProtectedRoute>}/>
      <Route path="/dashboard/runs/:runId/report" element={<ProtectedRoute><Clause44Run/></ProtectedRoute>}/>
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
