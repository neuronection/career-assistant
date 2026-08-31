import axios from "axios";

export const TOKEN_KEY = "mja_token";

export const api = axios.create({ baseURL: "/api/v1" });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !location.pathname.startsWith("/login")) {
      localStorage.removeItem(TOKEN_KEY);
      if (!location.pathname.startsWith("/register")) location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export function apiDetail(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return (error.response?.data?.detail as string) ?? error.message;
  }
  return String(error);
}
