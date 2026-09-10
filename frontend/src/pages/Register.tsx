import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/stores/authStore";
import { apiDetail } from "@/api/client";

export function Register() {
  const { t } = useTranslation();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const { register, loading } = useAuthStore();
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await register(email, password, fullName);
      navigate("/onboarding");
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-2xl border border-slate-200 p-6 space-y-4">
        <div className="flex items-center gap-2.5">
          <img src="/icon-light.svg" alt={t("app.logoAlt")} className="w-10 h-10 rounded-xl" />
          <div>
            <h1 className="text-xl font-bold text-slate-900 leading-tight">
              {t("app.name")}
            </h1>
            <p className="text-xs text-slate-400">{t("auth.registerTagline")}</p>
          </div>
        </div>
        <input
          placeholder={t("auth.fullName")}
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
        />
        <input
          type="email"
          required
          placeholder={t("auth.email")}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
        />
        <input
          type="password"
          required
          minLength={8}
          placeholder={t("auth.passwordMin")}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
        />
        {error && <p className="text-sm text-rose-600">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-primary-600 hover:bg-primary-700 text-white rounded-lg py-2 text-sm font-medium disabled:opacity-50"
        >
          {t("auth.register")}
        </button>
        <p className="text-sm text-slate-500 text-center">
          {t("auth.haveAccount")}{" "}
          <Link to="/login" className="text-primary-700 font-medium">
            {t("auth.signIn")}
          </Link>
        </p>
      </form>
    </div>
  );
}
