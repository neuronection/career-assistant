import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { initI18n } from "./lib/i18n";
import "@neuronection/assistant-ui/styles.css";
import "./index.css";
import "./styles/motion.css";
import "./theme.css";

void initI18n();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
