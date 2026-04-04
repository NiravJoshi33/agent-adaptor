import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";

export function Shell() {
  return (
    <div className="relative min-h-screen lg:grid lg:grid-cols-[280px_1fr]">
      <Sidebar />
      <main className="relative min-h-screen">
        <div className="mx-auto max-w-container px-6 py-10 sm:px-10 lg:px-12">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
