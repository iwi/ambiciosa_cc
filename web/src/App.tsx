import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Analyse from "./pages/Analyse";
import Play from "./pages/Play";
import Simulate from "./pages/Simulate";
import Strategies from "./pages/Strategies";

const NAV = [
  ["/play", "Play"],
  ["/simulate", "Simulate"],
  ["/strategies", "Strategies"],
  ["/analyse", "Analyse"],
] as const;

export default function App() {
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <NavLink to="/play" className="wordmark" aria-label="Ambiciosa, home">
          <span className="wm-die" aria-hidden="true">A</span>
          Ambiciosa
        </NavLink>
        <nav aria-label="Main">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to}>{label}</NavLink>
          ))}
        </nav>
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<Navigate to="/play" replace />} />
          <Route path="/play" element={<Play />} />
          <Route path="/simulate" element={<Simulate />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/analyse" element={<Analyse />} />
          <Route path="*" element={<div className="page"><h1>Not found</h1><p>That page does not exist. Use the menu above.</p></div>} />
        </Routes>
      </main>
    </>
  );
}
