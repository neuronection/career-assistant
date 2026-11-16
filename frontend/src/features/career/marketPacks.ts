export type MarketId = "uk" | "de" | "at" | "ch";
export type MarketSection = "cv" | "norms" | "cycle";

export interface MarketSource {
  labelKey: string;
  url: string;
  section: MarketSection;
}

export interface MarketPack {
  id: MarketId;
  sources: MarketSource[];
}

export const MARKET_GUIDE_REVIEWED = "2026-11-12";

export const GRADE_SOURCES: MarketSource[] = [
  {
    labelKey: "marketGuide.grades.sources.enic",
    url: "https://www.enic.org.uk/",
    section: "norms",
  },
  {
    labelKey: "marketGuide.grades.sources.anabin",
    url: "https://anabin.kmk.org/anabin.html",
    section: "norms",
  },
];

export const MARKETS: MarketPack[] = [
  {
    id: "uk",
    sources: [
      {
        labelKey: "marketGuide.sources.nationalCareers",
        url: "https://nationalcareers.service.gov.uk/careers-advice/cv-sections",
        section: "cv",
      },
      {
        labelKey: "marketGuide.sources.prospectsSchemes",
        url: "https://www.prospects.ac.uk/careers-advice/getting-a-job/graduate-schemes/",
        section: "norms",
      },
      {
        labelKey: "marketGuide.sources.prospectsSchemes",
        url: "https://www.prospects.ac.uk/careers-advice/getting-a-job/graduate-schemes/",
        section: "cycle",
      },
    ],
  },
  {
    id: "de",
    sources: [
      {
        labelKey: "marketGuide.sources.arbeitsagenturCv",
        url: "https://www.arbeitsagentur.de/arbeitslos-arbeit-finden/bewerbungstraining/bewerbung-schreiben",
        section: "cv",
      },
      {
        labelKey: "marketGuide.sources.arbeitsagenturLetter",
        url: "https://www.arbeitsagentur.de/vor-ort/zav/working-and-living-in-germany/iss-en/issue-02-2026/cover-letter",
        section: "norms",
      },
      {
        labelKey: "marketGuide.sources.arbeitsagenturAttachments",
        url: "https://www.arbeitsagentur.de/vor-ort/zav/working-and-living-in-germany/iss-en/issue-05-2026/attachments",
        section: "norms",
      },
      {
        labelKey: "marketGuide.sources.arbeitsagenturTraining",
        url: "https://www.arbeitsagentur.de/bildung/bewerbung/bewerbungsprozess-ausbildung",
        section: "cycle",
      },
      {
        labelKey: "marketGuide.sources.arbeitsagenturCalendar",
        url: "https://www.arbeitsagentur.de/bildung/einfach-erklaert/schritt5-ausbildungsplatz-suche-einfach",
        section: "cycle",
      },
    ],
  },
  {
    id: "at",
    sources: [
      {
        labelKey: "marketGuide.sources.amsCv",
        url: "https://www.ams.at/arbeitsuchende/richtig-bewerben/ansprechender-lebenslauf",
        section: "cv",
      },
      {
        labelKey: "marketGuide.sources.amsDossier",
        url: "https://www.ams.at/arbeitsuchende/richtig-bewerben/bewerbungsmappe",
        section: "norms",
      },
      {
        labelKey: "marketGuide.sources.amsApprenticeship",
        url: "https://www.ams.at/arbeitsuchende/topicliste/bewerbung-lehrstelle",
        section: "cycle",
      },
      {
        labelKey: "marketGuide.sources.migrationAustria",
        url: "https://www.migration.gv.at/en/living-and-working-in-austria/",
        section: "norms",
      },
    ],
  },
  {
    id: "ch",
    sources: [
      {
        labelKey: "marketGuide.sources.orientationCv",
        url: "https://www.orientation.ch/fr/creer-un-curriculum-vitae",
        section: "cv",
      },
      {
        labelKey: "marketGuide.sources.orientationDossier",
        url: "https://www.orientation.ch/fr/creer-et-envoyer-un-dossier-de-candidature",
        section: "norms",
      },
      {
        labelKey: "marketGuide.sources.orientationDossier",
        url: "https://www.orientation.ch/fr/creer-et-envoyer-un-dossier-de-candidature",
        section: "cv",
      },
      {
        labelKey: "marketGuide.sources.swissWorking",
        url: "https://www.ch.ch/en/foreign-nationals-in-switzerland/working-in-switzerland/",
        section: "norms",
      },
      {
        labelKey: "marketGuide.sources.orientationApprenticeship",
        url: "https://www.orientation.ch/fr/faire-un-apprentissage-en-suisse",
        section: "cycle",
      },
      {
        labelKey: "marketGuide.sources.orientationDossier",
        url: "https://www.orientation.ch/fr/creer-et-envoyer-un-dossier-de-candidature",
        section: "cycle",
      },
    ],
  },
];

export const GRADE_ROWS = ["first", "upperSecond", "lowerSecond", "third"] as const;
