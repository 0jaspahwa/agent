import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

export const KIT_LOADED_EVENT = "corvo:kit-loaded";

// Shown on every screen while the task kit is not loaded (the kit is not in the repo; /api/health says so).
// If the health check itself fails, nothing is shown: the screens report their own errors.
export default function KitBanner({ role }) {
  const [health, setHealth] = useState(null);
  useEffect(() => {
    const check = () => api("/api/health").then(setHealth, () => setHealth(null));
    check();
    window.addEventListener(KIT_LOADED_EVENT, check);
    return () => window.removeEventListener(KIT_LOADED_EVENT, check);
  }, []);
  if (!health || health.kit_loaded !== false) return null;
  return (
    <div className="banner" role="status">
      <b>{health.notice || "No kit data loaded. Procurement: load it under Load kit data."}</b>
      {role === "Procurement" && <> <Link to="/kit">Load kit data</Link></>}
    </div>
  );
}
