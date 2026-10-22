import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { Landing } from "./Landing";
import "./index.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });

// "/" is the landing page and "/app" the app; links from before the landing page (/?view=…, /?run=…) open the app
const inApp = () => window.location.pathname.startsWith("/app") || /[?&](view|run|job|tab|study|mode)=/.test(window.location.search);

function Root() {
  const [app, setApp] = useState(inApp);
  useEffect(() => {
    const sync = () => setApp(inApp());
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  if (!app) return <Landing onEnter={() => { window.history.pushState(null, "", "/app"); setApp(true); }} />;
  return <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Root />
    </QueryClientProvider>
  </StrictMode>,
);
