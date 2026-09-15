import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import DemoPage from "./DemoPage";
import "./styles.css";
import "./workbench.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname === "/demo" ? <DemoPage /> : <App />}
  </React.StrictMode>,
);
