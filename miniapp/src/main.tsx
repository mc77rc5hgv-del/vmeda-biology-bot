import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { initTelegramApp } from "./lib/telegram";
import "./styles/global.css";

// HashRouter, не BrowserRouter — Mini App отдаётся статическим хостингом без серверного
// перенаправления неизвестных путей на index.html; hash-роутинг работает при прямом обновлении
// страницы/глубокой ссылке без отдельной конфигурации сервера.

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function Root() {
  useEffect(() => {
    initTelegramApp();
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <App />
      </HashRouter>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
