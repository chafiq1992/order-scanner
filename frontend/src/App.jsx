import { useState } from "react";
import Scanner from "./components/Scanner.jsx";

export default function App() {
  const [summary, setSummary] = useState({});
  return (
    <main className="min-h-screen p-6 flex flex-col items-center gap-6 bg-gradient-to-br from-indigo-500 to-purple-600">
      <h1 className="text-white text-4xl font-extrabold drop-shadow">📦 Order Scanner</h1>
      <Scanner onSummary={setSummary} />
      <section className="flex flex-wrap gap-2 justify-center">
        {Object.entries(summary).map(([tag, n]) => (
          <span key={tag}
                className="px-4 py-1 rounded-full font-bold text-lg shadow"
                style={{background: tagColor(tag)}}>
            {n} × {tag}
          </span>
        ))}
      </section>
    </main>
  );
}

function tagColor(tag){
  const c = {k:"#ffc0cb",big:"#fff176","12livery":"#a5d6a7","12livrey":"#a5d6a7",
             fast:"#90caf9",oscario:"#40e0d0",sand:"#ffcc80"};
  return c[tag]||"#f28b82";
}
