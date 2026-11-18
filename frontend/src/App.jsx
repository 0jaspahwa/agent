import { useState } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { setApiIdentity } from "./api.js";
import { loadIdentity, saveIdentity } from "./identity.js";
import KitBanner from "./components/KitBanner.jsx";
import Identity from "./pages/Identity.jsx";
import { SCREENS, homeFor } from "./screens.jsx";

// Routes and navigation. Each role sees only its own screens (screens.jsx), so no tab or button is dead.
export default function App({ initialIdentity = loadIdentity(), Router = BrowserRouter, routerProps = {} }) {
  const [identity, setIdentity] = useState(() => {
    setApiIdentity(initialIdentity);
    return initialIdentity;
  });
  const [changing, setChanging] = useState(false);

  function choose(value) {
    saveIdentity(value);
    setApiIdentity(value);
    setIdentity(value);
    setChanging(false);
  }

  if (!identity || changing) return <Identity current={identity} onDone={choose} />;
  const mine = SCREENS.filter((s) => s.roles.includes(identity.role));
  return (
    <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }} {...routerProps}>
      <header className="top">
        <span className="brand">Corvo procurement</span>
        <nav>
          {mine.filter((s) => s.label).map((s) => <NavLink key={s.path} to={s.path}>{s.label}</NavLink>)}
        </nav>
        <span className="who">
          {identity.name} · {identity.role} <button type="button" className="link" onClick={() => setChanging(true)}>Change</button>
        </span>
      </header>
      <KitBanner role={identity.role} />
      <Routes>
        {mine.map((s) => <Route key={s.path} path={s.path} element={s.element} />)}
        <Route path="*" element={<Navigate to={homeFor(identity.role)} replace />} />
      </Routes>
    </Router>
  );
}
