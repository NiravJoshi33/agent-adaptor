import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Shell } from "@/components/layout/Shell";
import Login from "@/pages/Login";
import Overview from "@/pages/Overview";
import Capabilities from "@/pages/Capabilities";
import Agent from "@/pages/Agent";
import Operations from "@/pages/Operations";
import Metrics from "@/pages/Metrics";
import Prompt from "@/pages/Prompt";
import Wallet from "@/pages/Wallet";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/dashboard/login" element={<Login />} />
        <Route element={<Shell />}>
          <Route path="/dashboard/" element={<Overview />} />
          <Route path="/dashboard/capabilities" element={<Capabilities />} />
          <Route path="/dashboard/agent" element={<Agent />} />
          <Route path="/dashboard/operations" element={<Operations />} />
          <Route path="/dashboard/metrics" element={<Metrics />} />
          <Route path="/dashboard/prompt" element={<Prompt />} />
          <Route path="/dashboard/wallet" element={<Wallet />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
