import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
// No stylesheet here. It is imported by `Staff.tsx` instead, because it is
// 645 KB of point-of-sale and every public portal used to download it.
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
