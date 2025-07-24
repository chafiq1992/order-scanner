import { useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";

// Allow using a relative URL when VITE_API_BASE_URL is undefined.
const apiBase = import.meta.env.VITE_API_BASE_URL || "";

const tagColors = {
  k: "#ffc0cb",
  big: "#fff176",
  "12livery": "#a5d6a7",
  "12livrey": "#a5d6a7",
  fast: "#90caf9",
  oscario: "#40e0d0",
  sand: "#ffcc80",
  none: "#f28b82",
};

export default function App() {
  const readerRef = useRef(null);
  const scannerRef = useRef(null);
  const [result, setResult] = useState(
    'Click "Start Scan" to begin scanning orders'
  );
  const [resultClass, setResultClass] = useState("");
  const [orders, setOrders] = useState([]);
  const [summary, setSummary] = useState({});
  const [filterTag, setFilterTag] = useState("");
  const [scanning, setScanning] = useState(false);
  const [showStart, setShowStart] = useState(true);
  const [showAgain, setShowAgain] = useState(false);

  useEffect(() => {
    fetchSummary();
    const stored = localStorage.getItem("orders");
    if (stored) {
      try {
        const list = JSON.parse(stored);
        const today = new Date().toISOString().slice(0, 10);
        setOrders(list.filter((o) => o.ts && o.ts.startsWith(today)));
      } catch {}
    }
  }, []);

  useEffect(() => {
    localStorage.setItem("orders", JSON.stringify(orders));
  }, [orders]);

  function startScanner() {
    setResult("📱 Point your camera at a QR code...");
    setResultClass("");
    setScanning(true);
    setShowStart(false);
    setShowAgain(false);

    let qr = scannerRef.current;
    const config = { fps: 10, qrbox: 250 };
    const onScan = (code) => {
      if (navigator.vibrate) navigator.vibrate(200);
      qr.pause(true);
      setScanning(false);
      setShowAgain(true);
      setResult("⏳ Processing scan...");
      processScan(code);
    };

    if (!qr) {
      qr = new Html5Qrcode(readerRef.current.id);
      scannerRef.current = qr;
      qr.start({ facingMode: "environment" }, config, onScan, () => {})
        .catch(() => {
          handleScanError("Camera access denied or not available");
          setScanning(false);
          setShowStart(true);
        });
    } else {
      qr.resume();
    }
  }

  async function processScan(barcode) {
    try {
      const resp = await fetch(`${apiBase}/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ barcode }),
      });
      const data = await resp.json();
      updateScanUI(data);
    } catch (e) {
      handleScanError("Server error");
    }
  }

  function handleScanError(msg) {
    setResult(`❌ Error: ${msg}`);
    setResultClass("result-error");
    playErrorSound();
  }

  function updateScanUI(data) {
    const { result: res, order, tag, ts } = data;
    setResult(`${statusIcon(res)} ${res}`);
    setResultClass(resultClassFrom(res));
    if (res.includes("✅")) {
      playSuccessSound();
    } else {
      playErrorSound();
    }
    addOrderToList({ result: res, order, tag, ts });
    fetchSummary();
  }

  function addOrderToList(item) {
    setOrders((prev) => [item, ...prev].slice(0, 20));
  }

  async function fetchSummary() {
    const res = await fetch(`${apiBase}/tag-summary`);
    const data = await res.json();
    setSummary(data);
  }

  const displayedOrders = filterTag
    ? orders.filter((o) => (o.tag || "").toLowerCase() === filterTag)
    : orders;

  return (
    <div className="container">
      <div className="header">
        <h1>📦 Order Scanner</h1>
        <div
          id="reader"
          ref={readerRef}
          className={scanning ? "scanning" : ""}
        ></div>
        <div id="result" className={resultClass}>
          {result}
        </div>
      </div>
      <div id="scan-log">
        <div className="section-header">
          <span>📋</span>Recent Scans
        </div>
        <ul id="orderList">
          {displayedOrders.map((o, i) => (
            <li key={i} className={`order-item ${statusClass(o.result)}`}>
              <div className="order-status">
                <span
                  className={`status-indicator ${statusClass(o.result)}`}
                ></span>
                {o.result}
              </div>
              <div className="order-details">
                <span
                  className={`order-tag ${statusClass(o.result)}`}
                >
                  {o.tag || "No tag"}
                </span>
                <span className="order-name">{o.order}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <div className="bottom-bar">
        <div className="section-header">
          <span>📊</span>Tag Summary
        </div>
        <div id="tagSummary">
          {Object.entries(summary)
            .sort((a, b) => b[1] - a[1])
            .map(([tag, count]) => (
              <span
                key={tag}
                className={`tag-count ${filterTag === tag.toLowerCase() ? "active" : ""}`}
                style={{ background: tagColors[tag] || tagColors["none"] }}
                onClick={() =>
                  setFilterTag((cur) => (cur === tag.toLowerCase() ? "" : tag.toLowerCase()))
                }
              >
                {count} × {tag}
              </span>
            ))}
          {Object.keys(summary).length === 0 && (
            <span style={{ color: "#6b7280", fontStyle: "italic" }}>
              No scans yet
            </span>
          )}
        </div>
        {showStart && (
          <button className="scan-btn" id="scanBtn" onClick={startScanner}>
            <span className="emoji">📷</span>Scan
          </button>
        )}
        {showAgain && (
          <button className="scan-btn" id="againBtn" onClick={startScanner}>
            <span className="emoji">🔄</span>Scan Again
          </button>
        )}
      </div>
      <audio id="successSound" preload="auto">
        <source
          src="data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEALB8AAFgWAQACABAAZGF0YQoGAACBhYqHbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt5Y0rBjiR1/LBciUFLYPQ8diJMwgZZ7zs5Y0rBzqS1/LDcSIEK4bT8tiKMwgZZ7vs5I4rBzqS2O3CcSIEK4bT8tiKMwgZZ7vs5Y4rBjmR2PD/////iYmJiYmJiYmJiYmJiYmJ"
          type="audio/wav"
        />
      </audio>
      <audio id="errorSound" preload="auto">
        <source
          src="data:audio/wav;base64,UklGRt4CAABXQVZFZm10IBAAAAABAAEAiBQAACIVAQACABAAZGF0YaQCAAC4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4jY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Njo6Ojo6Ojo6Ojo6Ojo6Ojo6Ojo6Ojo6Ojo6Ojo6Ojo6Ojo6Ojo6OjH5+fn5+fn5+fn5+fn5+fn5+fn5+fn5+fn5+fn5+fn5+fn5+fn5+"
          type="audio/wav"
        />
      </audio>
    </div>
  );
}

function statusIcon(r) {
  if (r.includes("✅")) return "✅";
  if (r.includes("⚠️")) return "⚠️";
  if (r.includes("❌")) return "❌";
  return "❓";
}

function resultClassFrom(r) {
  if (r.includes("✅")) return "result-success";
  if (r.includes("⚠️")) return "result-warning";
  if (r.includes("❌")) return "result-error";
  return "result-error";
}

function statusClass(r) {
  if (r.includes("✅")) return "success";
  if (r.includes("⚠️")) return "warning";
  return "error";
}

function playSuccessSound() {
  const audio = document.getElementById("successSound");
  if (!audio) return;
  audio.currentTime = 0;
  audio.play().catch(() => {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
  });
}

function playErrorSound() {
  const audio = document.getElementById("errorSound");
  if (!audio) return;
  audio.currentTime = 0;
  audio.play().catch(() => {
    if (navigator.vibrate) navigator.vibrate([200, 100, 200, 100, 200]);
  });
}
