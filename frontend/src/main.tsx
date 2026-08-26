import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";
import { startTheme } from "./theme";

// After the inline script in index.html has already painted, so this is not what
// prevents the flash. It attaches the device listener and re-asserts the
// attribute, which matters if the inline script was ever blocked.
startTheme();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
