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

function textColor(bg) {
  if (!bg) return "#000";
  let c = bg.replace("#", "");
  if (c.length === 3) {
    c = c.split("").map((x) => x + x).join("");
  }
  const r = parseInt(c.substr(0, 2), 16);
  const g = parseInt(c.substr(2, 2), 16);
  const b = parseInt(c.substr(4, 2), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? "#000" : "#fff";
}

export default function App() {
  const readerRef = useRef(null);
  const scannerRef = useRef(null);
  const [result, setResult] = useState(
    'Click "Start Scan" to begin scanning orders'
  );
  const [resultClass, setResultClass] = useState("");
  const [orders, setOrders] = useState([]);
  const [summary, setSummary] = useState({});
  const [showReader, setShowReader] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [showStart, setShowStart] = useState(true);
  const [showAgain, setShowAgain] = useState(false);
  const [filterTag, setFilterTag] = useState("");
  const touchStartY = useRef(null);

  useEffect(() => {
    fetchSummary();
  }, []);

  function startScanner() {
    setResult("📱 Point your camera at a QR code...");
    setResultClass("");
    setShowReader(true);
    setScanning(true);
    setShowStart(false);
    setShowAgain(false);

    const qr = new Html5Qrcode(readerRef.current.id);
    scannerRef.current = qr;
    qr.start(
      { facingMode: "environment" },
      { fps: 10, qrbox: 250 },
      (code) => {
        if (navigator.vibrate) navigator.vibrate(200);
        qr.stop().then(() => {
          setShowReader(false);
          setScanning(false);
          setShowAgain(true);
          setResult("⏳ Processing scan...");
          processScan(code);
        });
      },
      () => {}
    ).catch(() => {
      handleScanError("Camera access denied or not available");
      setShowReader(false);
      setScanning(false);
      setShowStart(true);
    });
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
    const { result: res, order, tag } = data;
    setResult(`${statusIcon(res)} ${res}`);
    setResultClass(resultClassFrom(res));
    if (res.includes("✅")) {
      playSuccessSound();
    } else {
      playErrorSound();
    }
    addOrderToList({ result: res, order, tag });
    fetchSummary();
  }

  function addOrderToList(item) {
    setOrders((prev) => [item, ...prev.slice(0, 19)]);
  }

  async function fetchSummary() {
    const res = await fetch(`${apiBase}/tag-summary`);
    const data = await res.json();
    setSummary(data);
  }

  const filteredOrders = filterTag
    ? orders.filter((o) => o.tag === filterTag)
    : orders;

  const totalCount = Object.values(summary).reduce((a, b) => a + b, 0);

  function handleTagClick(tag) {
    setFilterTag(tag);
  }

  function onTouchStart(e) {
    if (e.touches.length === 1) {
      touchStartY.current = e.touches[0].clientY;
    }
  }

  function onTouchEnd(e) {
    if (touchStartY.current !== null) {
      const dy = e.changedTouches[0].clientY - touchStartY.current;
      if (dy > 50) {
        fetchSummary();
      }
      touchStartY.current = null;
    }
  }


  return (
    <div className="container">
      <div className="header">
        <h1>📦 Order Scanner</h1>
        <div
          id="reader"
          ref={readerRef}
          className={scanning ? "scanning" : ""}
          style={{ display: showReader ? "block" : "none" }}
        ></div>
        <div id="result" className={resultClass}>
          {result}
        </div>
        {showStart && (
          <button className="scan-btn" id="scanBtn" onClick={startScanner}>
            <span className="emoji">📷</span>Start Scan
          </button>
        )}
        {showAgain && (
          <button className="scan-btn" id="againBtn" onClick={startScanner}>
            <span className="emoji">🔄</span>Scan Another
          </button>
        )}
      </div>
      <div id="scan-log" onDoubleClick={() => setFilterTag("")}>
        <div className="section-header">
          <span>📋</span>Recent Scans
        </div>
        <ul
          id="orderList"
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
        >
          {filteredOrders.map((o, i) => (
            <li key={i} className={`order-item ${statusClass(o.result)}`}>
              <div className="order-status">
                <span
                  className={`status-indicator ${statusClass(o.result)}`}
                ></span>
                {o.result}
              </div>
              <div className="order-details">
                <span
                  className="order-tag"
                  style={{
                    background: tagColors[o.tag] || tagColors["none"],
                    color: textColor(tagColors[o.tag] || tagColors["none"]),
                  }}
                >
                  {o.tag || "No tag"}
                </span>
                <span className="order-name">{o.order}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <div id="tagBar">
        <span
          className={`tag-chip ${filterTag === "" ? "active" : ""}`}
          onClick={() => handleTagClick("")}
        >
          ALL ({totalCount})
        </span>
        {Object.entries(summary)
          .sort((a, b) => b[1] - a[1])
          .map(([tag, count]) => (
            <span
              key={tag}
              className={`tag-chip ${filterTag === tag ? "active" : ""}`}
              style={{
                background: tagColors[tag] || tagColors["none"],
                color: textColor(tagColors[tag] || tagColors["none"]),
              }}
              onClick={() => handleTagClick(tag)}
            >
              {tag.toUpperCase()} ({count})
            </span>
          ))}
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
