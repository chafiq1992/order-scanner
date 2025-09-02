import { useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";

// Allow using a relative URL when VITE_API_BASE_URL is undefined.
const apiBase = import.meta.env.VITE_API_BASE_URL || "";

const tagColors = {
  k: "#ffc0cb",
  big: "#fff176",
  "12livery": "#a5d6a7",
  fast: "#90caf9",
  oscario: "#40e0d0",
  sand: "#ffcc80",
  none: "#f28b82",
};

// Map tag variants to their canonical form.  Keys and values should be lowercase.
const tagSynonyms = {
  k: "k",
  big: "big",
  "12livery": "12livery",
  "12livrey": "12livery",
  "12 livery": "12livery",
  fast: "fast",
  oscario: "oscario",
  sand: "sand",
  sandy: "sand",
};

export default function App() {
  const readerRef = useRef(null);
  const scannerRef = useRef(null);
  const [tab, setTab] = useState("scan");
  const [result, setResult] = useState("");
  const [resultClass, setResultClass] = useState("");
  const [orders, setOrders] = useState([]);
  const [summary, setSummary] = useState({});
  const [updatedTags, setUpdatedTags] = useState({});
  const [scanning, setScanning] = useState(false);
  const [showStart, setShowStart] = useState(true);
  const [showAgain, setShowAgain] = useState(false);
  const [scanRows, setScanRows] = useState([]);
  const [scanDate, setScanDate] = useState(new Date().toISOString().slice(0, 10));
  const [scanTag, setScanTag] = useState("");
  const [toast, setToast] = useState("");
  const [flashRow, setFlashRow] = useState(null);

  useEffect(() => {
    fetchSummary();
    const id = setInterval(fetchSummary, 5000);
    const stored = localStorage.getItem("orders");
    if (stored) {
      try {
        const list = JSON.parse(stored);
        const today = new Date().toISOString().slice(0, 10);
        setOrders(list.filter((o) => o.ts && o.ts.startsWith(today)));
      } catch {}
    }
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    localStorage.setItem("orders", JSON.stringify(orders));
  }, [orders]);

  useEffect(() => {
    if (tab === "list") {
      fetchScans();
    }
  }, [tab, scanDate, scanTag]);

  function hideLibraryInfo() {
    const root = readerRef.current;
    if (!root) return;
    const infoIcon = root.querySelector('img[alt="Info icon"]');
    if (infoIcon) infoIcon.remove();
    root.querySelectorAll('div').forEach((d) => {
      if (d.textContent && d.textContent.includes('Powered by')) {
        d.remove();
      }
    });
  }

  function startScanner() {
    setResult("");
    setResultClass("");
    setScanning(true);
    setShowStart(false);
    setShowAgain(false);

    let qr = scannerRef.current;
    const config = {
      fps: 15,
      qrbox: (vw, vh) => {
        const size = Math.floor(Math.min(vw, vh) * 0.8);
        return { width: size, height: size };
      },
      experimentalFeatures: { useBarCodeDetectorIfSupported: true },
      disableFlip: true,
    };
    const onScan = (code) => {
      if (navigator.vibrate) navigator.vibrate(100);
      setResult("⏳ Processing scan...");
      qr.pause(true);
      setScanning(false);
      // Show instantly in the list
      addOrderToList({ result: "⏳ Processing", order: code, tag: "", ts: new Date().toISOString() });
      processScan(code);
      setShowAgain(true);
    };

    const handleStartError = () => {
      if (qr) {
        qr.stop().catch(() => {});
        qr.clear();
      }
      handleScanError("Camera access denied or not available");
      setScanning(false);
      setShowStart(true);
    };

    const verifyVideo = () => {
      setTimeout(() => {
        const root = readerRef.current;
        if (!root) return;
        const vid = root.querySelector("video");
        if (!vid || !vid.videoWidth || !vid.videoHeight) {
          handleStartError();
        }
      }, 500);
    };

    const startNew = () => {
      qr
        .start({ facingMode: "environment" }, config, onScan, () => {})
        .then(() => {
          hideLibraryInfo();
          verifyVideo();
        })
        .catch(handleStartError);
    };

    if (!qr) {
      qr = new Html5Qrcode(readerRef.current.id);
      scannerRef.current = qr;
      startNew();
    } else {
      qr
        .resume()
        .then(() => {
          hideLibraryInfo();
          verifyVideo();
        })
        .catch(() => {
          qr.stop().catch(() => {});
          qr.clear();
          qr = new Html5Qrcode(readerRef.current.id);
          scannerRef.current = qr;
          startNew();
        });
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
    // Replace the placeholder if present, otherwise prepend
    setOrders((prev) => {
      if (prev.length && (prev[0].result || "").startsWith("⏳")) {
        const [_first, ...rest] = prev;
        return [{ result: res, order, tag, ts }, ...rest].slice(0, 20);
      }
      return [{ result: res, order, tag, ts }, ...prev].slice(0, 20);
    });
    if (res.includes("Duplicate phone")) {
      setToast("⚠️ Duplicate phone in last 3 days");
      setTimeout(() => setToast(""), 2000);
    }
    fetchSummary();
  }

  function addOrderToList(item) {
    setOrders((prev) => [item, ...prev].slice(0, 20));
  }

  async function fetchSummary() {
    const url = new URL(`${apiBase}/tag-summary`, window.location.origin);
    url.searchParams.set("date", new Date().toISOString().slice(0, 10));
    const res = await fetch(url.toString());
    const data = await res.json();
    setSummary((prev) => {
      const changed = {};
      for (const [tag, count] of Object.entries(data)) {
        if (count > (prev[tag] || 0)) {
          changed[tag] = true;
        }
      }
      if (Object.keys(prev).length && Object.keys(changed).length) {
        setUpdatedTags((u) => ({ ...u, ...changed }));
        setTimeout(() => {
          setUpdatedTags((u) => {
            const copy = { ...u };
            for (const t of Object.keys(changed)) delete copy[t];
            return copy;
          });
        }, 600);
      }
      return data;
    });
  }

  async function fetchScans() {
    const url = new URL(`${apiBase}/scans`, window.location.origin);
    url.searchParams.set("date", scanDate);
    if (scanTag) url.searchParams.set("tag", scanTag);
    const res = await fetch(url.toString());
    const data = await res.json();
    setScanRows(data);
  }

  async function updateScan(id, payload) {
    const res = await fetch(`${apiBase}/scans/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      setToast("Saved \u2713");
      setFlashRow(id);
      setTimeout(() => setFlashRow(null), 1000);
      fetchScans();
      fetchSummary();
    }
  }

  async function deleteScan(id) {
    if (!confirm("Delete this scan?")) return;
    const res = await fetch(`${apiBase}/scans/${id}`, { method: "DELETE" });
    if (res.ok) {
      fetchScans();
      fetchSummary();
    }
  }

  const displayedOrders = orders;

  const listTagCounts = {};
  scanRows.forEach((r) => {
    const t = detectTag(r.tags);
    listTagCounts[t] = (listTagCounts[t] || 0) + 1;
  });

  const displayedList = scanTag
    ? scanRows.filter((r) => detectTag(r.tags) === scanTag)
    : scanRows;

  return (
    <div className="container">
      <div className="tab-bar">
        <button
          className={tab === "scan" ? "active" : ""}
          onClick={() => setTab("scan")}
        >
          Scan
        </button>
        <button
          className={tab === "list" ? "active" : ""}
          onClick={() => setTab("list")}
        >
          Scanned Orders
        </button>
      </div>
      {toast && <div className="toast">{toast}</div>}
      {tab === "scan" && (
        <>
          <div className="header">
            <h1>📦 Order Scanner</h1>
            <div
              id="reader"
              ref={readerRef}
              className={scanning ? "scanning" : ""}
            ></div>
            {result && (
              <div id="result" className={resultClass}>
                {result}
              </div>
            )}
          </div>
          <div id="scan-log">
            <div className="section-header">
              <span>📋</span>Recent Scans
            </div>
            <ul id="orderList">
              {displayedOrders.map((o, i) => (
                <li key={i} className={`order-item ${statusClass(o.result)}`}>
                  <span className="order-name">{o.order}</span>
                  <span
                    className="order-tag"
                    style={{ background: tagColors[(o.tag || "none").toLowerCase()] || tagColors["none"] }}
                  >
                    {o.tag || "No tag"}
                  </span>
                  <span className="order-status-text">{o.result}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="bottom-bar">
            <div id="tagSummary">
              {Object.entries(summary)
                .sort((a, b) => b[1] - a[1])
                .map(([tag, count]) => (
                  <div
                    key={tag}
                    className={`summary-box ${updatedTags[tag] ? "bump" : ""}`}
                    style={{ background: tagColors[tag] || tagColors["none"] }}
                  >
                    <div className="summary-name">{tag.toUpperCase()}</div>
                    <div className="summary-count">{count}</div>
                  </div>
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
        </>
      )}
      {tab === "list" && (
        <div className="table-card">
          <div className="filters">
            <input
              type="date"
              value={scanDate}
              onChange={(e) => setScanDate(e.target.value)}
            />
            <div className="tag-pills">
              <span
                className={`tag-pill ${scanTag === "" ? "active" : ""}`}
                onClick={() => setScanTag("")}
              >
                All ({scanRows.length})
              </span>
              {Object.entries(listTagCounts).map(([tag, count]) => (
                <span
                  key={tag}
                  className={`tag-pill ${scanTag === tag ? "active" : ""}`}
                  style={{ background: tagColors[tag] || tagColors["none"] }}
                  onClick={() =>
                    setScanTag((cur) => (cur === tag ? "" : tag))
                  }
                >
                  {tag.toUpperCase()} ({count})
                </span>
              ))}
            </div>
          </div>
          <table className="scans-table">
            <thead>
              <tr>
                <th>Order #</th>
                <th>Status</th>
                <th>Tag</th>
                <th>Scan Time</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {displayedList.map((r) => (
                <tr
                  key={r.id}
                  className={`${
                    !detectTag(r.tags) ? "missing-tag" : ""
                  } ${flashRow === r.id ? "flash" : ""}`}
                >
                  <td><strong>{r.order_name}</strong></td>
                  <td>
                    <select
                      value={r.status || ""}
                      onChange={(e) =>
                        updateScan(r.id, { status: e.target.value })
                      }
                    >
                      <option>Fulfilled</option>
                      <option>Unfulfilled</option>
                    </select>
                  </td>
                  <td>
                    <select
                      value={detectTag(r.tags)}
                      onChange={(e) => updateScan(r.id, { tags: e.target.value })}
                    >
                      {Object.keys(tagColors).map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{new Date(r.ts).toLocaleTimeString()}</td>
                  <td>
                    <button
                      className="delete-btn"
                      onClick={() => deleteScan(r.id)}
                    >
                      🗑️
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="totals">
            Total scanned today: {scanRows.length} orders |
            Current view: {displayedList.length}
            {scanTag ? ` ${scanTag.toUpperCase()}` : ""}
          </div>
        </div>
      )}
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

function detectTag(tagStr) {
  const tokens = (tagStr || "").split(/[,\s]+/).map((t) => t.toLowerCase().trim());
  for (const tok of tokens) {
    if (tagSynonyms[tok]) {
      return tagSynonyms[tok];
    }
  }
  return "";
}
