export default function StoriaDelCorsoPage() {
  const timelineData = [
    {
      id: "2025-10",
      mese: "Ottobre 2025",
      dataOrdine: "2025-10-01",
      materie: [
        "Gestione del processo formativo",
        "Soft Skills",
        "Fondamenti di programmazione"
      ],
      strumenti: ["PowerPoint", "PyCharm"],
      linguaggi: [],
      ambienti: [],
      descrizione:
        "Avvio del corso con lezioni teoriche e primi approcci alla programmazione.",
    },
    {
      id: "2025-11",
      mese: "Novembre 2025",
      dataOrdine: "2025-11-01",
      materie: [
        "Fondamenti di programmazione",
        "Networking",
        "Sicurezza e prevenzione",
        "Inglese tecnico"
      ],
      strumenti: ["PyCharm", "Cisco Packet Tracer", "PowerPoint"],
      linguaggi: [],
      ambienti: [],
      descrizione:
        "Introduzione al networking e consolidamento della programmazione.",
    },
    {
      id: "2025-12",
      mese: "Dicembre 2025",
      dataOrdine: "2025-12-01",
      materie: ["Win OS", "Sviluppo distribuito"],
      strumenti: [
        "GitHub",
        "GitHub Desktop",
        "Visual Studio Code",
        "Bootstrap",
        "Tailwind"
      ],
      linguaggi: ["HTML", "CSS", "JavaScript"],
      ambienti: ["VMware", "Windows Server 2019"],
      descrizione:
        "Introduzione allo sviluppo web e ai sistemi Windows virtualizzati.",
    },
    {
      id: "2026-01",
      mese: "Gennaio 2026",
      dataOrdine: "2026-01-01",
      materie: [
        "Linguaggi web",
        "Database",
        "Python",
        "Sistemi di virtualizzazione"
      ],
      strumenti: [
        "Visual Studio Code",
        "Docker",
        "Docker Compose",
        "DockerHub",
        "Proxmox",
        "PostgreSQL"
      ],
      linguaggi: ["Python", "SQL"],
      ambienti: ["VMware", "Windows Server"],
      descrizione:
        "Sviluppo full stack e introduzione alla virtualizzazione con Docker e Proxmox.",
    },
    {
      id: "2026-02",
      mese: "Febbraio 2026",
      dataOrdine: "2026-02-01",
      materie: ["Linux OS", "Security fundamentals", "Cloud Services"],
      strumenti: ["Docker", "Proxmox"],
      linguaggi: ["Node-RED"],
      ambienti: ["VMware", "Ubuntu", "Kali Linux", "Debian", "AWS"],
      descrizione:
        "Focus su Linux, sicurezza e prime esperienze nel cloud AWS.",
    },
    {
      id: "2026-03",
      mese: "Marzo 2026",
      dataOrdine: "2026-03-01",
      materie: [
        "Security fundamentals",
        "Cloud Services",
        "Project Work",
        "Architettura IT",
        "Storage"
      ],
      strumenti: ["Agile", "Scrum"],
      linguaggi: [],
      ambienti: ["VMware", "AWS", "ESXi"],
      descrizione:
        "Consolidamento su sicurezza e cloud con introduzione al project work e infrastrutture.",
    },
    {
      id: "2026-04",
      mese: "Aprile 2026",
      dataOrdine: "2026-04-01",
      materie: ["Scripting (PowerShell e Bash)", "Cloud Services", "Storage"],
      strumenti: [],
      linguaggi: ["PowerShell", "Bash"],
      ambienti: ["AWS", "ESXi"],
      descrizione:
        "Automazione tramite scripting e gestione avanzata di infrastrutture cloud.",
    },
    {
      id: "2026-05",
      mese: "Maggio 2026",
      dataOrdine: "2026-05-01",
      materie: ["Cloud Services", "Gestione del processo formativo"],
      strumenti: ["PowerPoint"],
      linguaggi: [],
      ambienti: ["AWS"],
      descrizione:
        "Approfondimento finale sul cloud e revisione del percorso formativo.",
    },
    {
      id: "2026-06",
      mese: "Giugno 2026",
      dataOrdine: "2026-06-01",
      materie: [],
      strumenti: [],
      linguaggi: [],
      ambienti: [],
      descrizione: "Contenuti non ancora disponibili.",
    },
    {
      id: "2026-07",
      mese: "Luglio 2026",
      dataOrdine: "2026-07-01",
      materie: [],
      strumenti: [],
      linguaggi: [],
      ambienti: [],
      descrizione: "Contenuti non ancora disponibili.",
    },
    {
      id: "2026-08",
      mese: "Agosto 2026",
      dataOrdine: "2026-08-01",
      materie: [],
      strumenti: [],
      linguaggi: [],
      ambienti: [],
      descrizione: "Contenuti non ancora disponibili.",
    },
    {
      id: "2026-09",
      mese: "Settembre 2026",
      dataOrdine: "2026-09-01",
      materie: [],
      strumenti: [],
      linguaggi: [],
      ambienti: [],
      descrizione: "Contenuti non ancora disponibili.",
    },
    {
      id: "2026-10",
      mese: "Ottobre 2026",
      dataOrdine: "2026-10-01",
      materie: [],
      strumenti: [],
      linguaggi: [],
      ambienti: [],
      descrizione: "Contenuti non ancora disponibili.",
    },
    {
      id: "2026-11",
      mese: "Novembre 2026",
      dataOrdine: "2026-11-01",
      materie: [],
      strumenti: [],
      linguaggi: [],
      ambienti: [],
      descrizione: "Contenuti non ancora disponibili.",
    },
    {
      id: "2026-12",
      mese: "Dicembre 2026",
      dataOrdine: "2026-12-01",
      materie: [],
      strumenti: [],
      linguaggi: [],
      ambienti: [],
      descrizione: "Contenuti non ancora disponibili.",
    },
  ];

  const currentMonth = "2026-03";

  const getStatus = (id) => {
    if (id < currentMonth) return "completed";
    if (id === currentMonth) return "current";
    return "future";
  };

  const statusStyles = {
    completed: {
      dot: "bg-emerald-500 ring-emerald-200",
      line: "bg-emerald-400",
      badge: "bg-emerald-50 text-emerald-700 border-emerald-200",
    },
    current: {
      dot: "bg-sky-500 ring-sky-200",
      line: "bg-sky-300",
      badge: "bg-sky-50 text-sky-700 border-sky-200",
    },
    future: {
      dot: "bg-slate-300 ring-slate-200",
      line: "bg-slate-200",
      badge: "bg-slate-50 text-slate-600 border-slate-200",
    },
  };

  const Section = ({ title, items, emptyText }) => (
    <div>
      <h4 className="mb-2 text-sm font-semibold text-slate-800">{title}</h4>
      {items.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {items.map((item) => (
            <span
              key={item}
              className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700"
            >
              {item}
            </span>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-500">{emptyText}</p>
      )}
    </div>
  );

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white p-6 md:p-10">
      <div className="mx-auto max-w-7xl">
        <div className="mb-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="mb-2 text-sm font-medium uppercase tracking-[0.2em] text-sky-700">
                Servizio 1
              </p>
              <h1 className="text-3xl font-bold tracking-tight text-slate-900 md:text-4xl">
                Storia del corso
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600 md:text-base">
                Timeline dinamica con un nodo per ogni mese, dall&apos;inizio del corso fino alla fine del 2026.
                Passando il mouse sopra ciascun nodo si apre un fumetto con materie,
                strumenti, linguaggi e ambienti scoperti durante le lezioni.
              </p>
            </div>

            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-emerald-700">
                Completato
              </span>
              <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1.5 text-sky-700">
                Mese corrente
              </span>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-slate-600">
                Futuro
              </span>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="min-w-[1450px] p-8">
            <div className="relative flex items-start justify-between gap-6 pt-14">
              <div className="absolute left-0 right-0 top-16 h-1 rounded-full bg-slate-200" />

              {timelineData.map((item, index) => {
                const status = getStatus(item.id);
                const styles = statusStyles[status];
                const hasContent =
                  item.materie.length ||
                  item.strumenti.length ||
                  item.linguaggi.length ||
                  item.ambienti.length;

                return (
                  <div
                    key={item.id}
                    className="group relative z-10 flex w-[96px] shrink-0 flex-col items-center text-center"
                  >
                    {index < timelineData.length - 1 && (
                      <div
                        className={`absolute left-[48px] top-[16px] h-1 w-[calc(100%+24px)] rounded-full ${styles.line}`}
                      />
                    )}

                    <div
                      className={`relative h-8 w-8 rounded-full ring-8 transition-transform duration-200 group-hover:scale-110 ${styles.dot}`}
                    />

                    <span
                      className={`mt-4 rounded-full border px-2.5 py-1 text-[11px] font-medium ${styles.badge}`}
                    >
                      {status === "completed"
                        ? "Completato"
                        : status === "current"
                          ? "Corrente"
                          : "Futuro"}
                    </span>

                    <div className="mt-3 text-sm font-semibold text-slate-900">
                      {item.mese.split(" ")[0]}
                    </div>
                    <div className="text-xs text-slate-500">{item.mese.split(" ")[1]}</div>

                    <div className="pointer-events-none absolute left-1/2 top-full z-30 mt-5 hidden w-[350px] -translate-x-1/2 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-2xl group-hover:block">
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div>
                          <h3 className="text-base font-bold text-slate-900">{item.mese}</h3>
                          <p className="mt-1 text-sm text-slate-600">{item.descrizione}</p>
                        </div>
                        <span
                          className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium ${styles.badge}`}
                        >
                          {hasContent ? "Attività presenti" : "In aggiornamento"}
                        </span>
                      </div>

                      <div className="space-y-4">
                        <Section
                          title="📚 Materie"
                          items={item.materie}
                          emptyText="Nessuna materia registrata per questo mese."
                        />
                        <Section
                          title="🛠️ Strumenti"
                          items={item.strumenti}
                          emptyText="Nessuno strumento registrato."
                        />
                        <Section
                          title="💻 Linguaggi"
                          items={item.linguaggi}
                          emptyText="Nessun linguaggio registrato."
                        />
                        <Section
                          title="🖥️ Ambienti"
                          items={item.ambienti}
                          emptyText="Nessun ambiente registrato."
                        />
                      </div>

                      <div className="absolute left-1/2 top-0 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rotate-45 border-l border-t border-slate-200 bg-white" />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-slate-900">Timeline dinamica</div>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Un nodo per ogni mese, dal mese iniziale del corso fino a dicembre 2026.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-slate-900">Tooltip informativo</div>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Al passaggio del mouse si apre un fumetto con tutte le informazioni raccolte.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-slate-900">Facile da estendere</div>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              I dati possono essere letti da un&apos;API o da DynamoDB senza modificare la UI.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
