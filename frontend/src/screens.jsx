// Which screens exist, and which roles can use them. The navigation and the routes are built from this list
// only, so a role never sees a tab it cannot use. The server checks the role again on every action.
import Chat from "./pages/Chat.jsx";
import MyRequests from "./pages/MyRequests.jsx";
import Workspace from "./pages/Workspace.jsx";
import Batches from "./pages/Batches.jsx";
import Contracts from "./pages/Contracts.jsx";
import Policies from "./pages/Policies.jsx";
import PolicyDetail from "./pages/PolicyDetail.jsx";
import Preferred from "./pages/Preferred.jsx";
import Audit from "./pages/Audit.jsx";
import KitData from "./pages/KitData.jsx";

const REQUESTERS = ["Requester", "Procurement"];
const BUYERS = ["Buyer", "Procurement"];

export const SCREENS = [
  { path: "/workspace", label: "Workspace", roles: BUYERS, element: <Workspace /> },
  { path: "/batches", label: "Batches", roles: BUYERS, element: <Batches /> },
  { path: "/contracts", label: "Contracts", roles: BUYERS, element: <Contracts /> },
  { path: "/suppliers", label: "Preferred suppliers", roles: BUYERS, element: <Preferred /> },
  { path: "/policies", label: "Policy", roles: ["Procurement"], element: <Policies /> },
  { path: "/policies/:id", label: null, roles: ["Procurement"], element: <PolicyDetail /> },
  { path: "/audit", label: "Audit log", roles: BUYERS, element: <Audit /> },
  { path: "/kit", label: "Load kit data", roles: ["Procurement"], element: <KitData /> },
  { path: "/chat", label: "New request", roles: REQUESTERS, element: <Chat /> },
  { path: "/requests", label: "My requests", roles: REQUESTERS, element: <MyRequests /> },
];

const HOME = { Requester: "/chat", Buyer: "/workspace", Procurement: "/workspace" };

export function homeFor(role) {
  return HOME[role] || "/";
}
