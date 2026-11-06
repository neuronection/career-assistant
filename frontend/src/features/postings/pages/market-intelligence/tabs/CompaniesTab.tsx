import { useNavigate } from "react-router-dom";

import { CompaniesCard } from "../cards";
import type { TabProps } from "./shared";

export function CompaniesTab({ data, view, loading, refresh }: TabProps) {
  const navigate = useNavigate();
  return (
    <CompaniesCard
      summary={data.companies_summary}
      overview={data.companies_overview}
      loading={loading}
      summaryError={data.errors.companies_summary ?? null}
      overviewError={data.errors.companies_overview ?? null}
      onRetry={refresh}
      onNewCompanies={() => navigate("/companies?status=new")}
      onIndustry={(industry) => navigate(`/companies?industry=${encodeURIComponent(industry)}`)}
      onCompany={(key) => navigate(`/companies/${key}`)}
      windowName={view.window}
    />
  );
}
