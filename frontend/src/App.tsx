import { Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import StationDetailPage from "./pages/StationDetailPage";
import SessionsPage from "./pages/SessionsPage";

// Three routes (architektura 8.1).
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/stations/:id" element={<StationDetailPage />} />
      <Route path="/stations/:id/sessions" element={<SessionsPage />} />
    </Routes>
  );
}
