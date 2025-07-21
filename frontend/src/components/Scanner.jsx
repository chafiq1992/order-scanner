import { Html5Qrcode } from "html5-qrcode";
import { useEffect, useRef, useState } from "react";

export default function Scanner({ onSummary }) {
  const readerRef = useRef(null);
  const [result, setResult] = useState("");
  const [className, setClassName] = useState("");

  async function process(barcode) {
    setResult("⏳ Processing…");
    try {
      const r = await fetch(`${import.meta.env.VITE_API_BASE_URL}/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ barcode }),
      }).then((res) => res.json());

      setResult(`${statusIcon(r.result)} ${r.result}`);
      setClassName(resultClass(r.result));
      updateSummary();
    } catch (e) {
      setResult("❌ Server error");
      setClassName("bg-red-200");
    }
  }

  function start() {
    const reader = new Html5Qrcode(readerRef.current.id);
    reader.start(
      { facingMode: "environment" },
      { fps: 10, qrbox: 250 },
      (code) => {
        reader.stop();
        process(code);
      }
    );
  }

  async function updateSummary() {
    const s = await fetch(
      `${import.meta.env.VITE_API_BASE_URL}/tag-summary`
    ).then((res) => res.json());
    onSummary(s);
  }

  useEffect(() => {
    updateSummary();
  }, []);

  return (
    <>
      <div
        id="reader"
        ref={readerRef}
        className="w-72 rounded-lg shadow-lg"
      ></div>
      <button
        onClick={start}
        className="mt-4 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-lg"
      >
        📷 Start Scan
      </button>
      <p
        className={`mt-4 text-xl font-semibold px-4 py-2 rounded-xl ${className}`}
      >
        {result}
      </p>
    </>
  );
}

function statusIcon(r) {
  return r.includes("✅") ? "✅" : r.includes("⚠️") ? "⚠️" : "❌";
}
function resultClass(r) {
  return r.includes("✅")
    ? "bg-green-100"
    : r.includes("⚠️")
    ? "bg-yellow-100"
    : "bg-red-100";
}
