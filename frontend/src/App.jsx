import { useEffect, useRef, useState } from "react";
import { jsPDF } from "jspdf";
import { Html5Qrcode, Html5QrcodeSupportedFormats } from "html5-qrcode";

// Allow using a relative URL when VITE_API_BASE_URL is undefined.
const apiBase = import.meta.env.VITE_API_BASE_URL || "";

const tagColors = {
  k: "#ffc0cb",
  big: "#fff176",
  "12livery": "#a5d6a7",
  fast: "#90caf9",
  oscario: "#40e0d0",
  meta: "#ffcc80",
  lx: "#d1c4e9",
  pal: "#ffd54f",
  l24: "#b2dfdb",
  ibex: "#b3e5fc",
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
  meta: "meta",
  sand: "meta",
  sandy: "meta",
  lx: "lx",
  pal: "pal",
  l24: "l24",
  ibex: "ibex",
};

function isIOS() {
  // Covers iPhone/iPad/iPod, including iPadOS reporting as Mac.
  const ua = navigator.userAgent || "";
  const platform = navigator.platform || "";
  return (
    /iPad|iPhone|iPod/i.test(ua) ||
    (platform === "MacIntel" && typeof navigator.maxTouchPoints === "number" && navigator.maxTouchPoints > 1)
  );
}

export default function App() {
  const readerRef = useRef(null);
  const scannerRef = useRef(null);
  const recentCodesRef = useRef(new Map()); // code -> lastSeenMs for dedup within a short window

  function pageFromPathname(pathname) {
    const p = String(pathname || "/").toLowerCase();
    if (p === "/return-scan" || p.startsWith("/return-scan/")) return "return";
    return "order";
  }

  // Two separate pages (routes):
  // - "/"              => order scanner app (existing)
  // - "/return-scan"   => return scanner app (separate UI + separate list)
  const [page, setPage] = useState(() => pageFromPathname(window.location.pathname));

  // Order-scanner tabs (only used on the order page)
  const [tab, setTab] = useState("scan");

  // Return-scanner tabs (only used on the return page)
  const [returnTab, setReturnTab] = useState("scan");
  const [result, setResult] = useState("");
  const [resultClass, setResultClass] = useState("");
  const [orders, setOrders] = useState([]);
  const [returnResult, setReturnResult] = useState("");
  const [returnResultClass, setReturnResultClass] = useState("");
  const [returnOrders, setReturnOrders] = useState([]); // recent "session" list (scan page)
  const [returnRows, setReturnRows] = useState([]); // DB-backed list (list page)
  const [returnDateStart, setReturnDateStart] = useState(new Date().toISOString().slice(0, 10));
  const [returnDateEnd, setReturnDateEnd] = useState("");
  const [summary, setSummary] = useState({});
  const [updatedTags, setUpdatedTags] = useState({});
  const [scanning, setScanning] = useState(false);
  const [showStart, setShowStart] = useState(true);
  const [showAgain, setShowAgain] = useState(false);
  const [returnScanning, setReturnScanning] = useState(false);
  const [returnShowStart, setReturnShowStart] = useState(true);
  const [returnShowAgain, setReturnShowAgain] = useState(false);
  const [scanRows, setScanRows] = useState([]);
  const [scanDate, setScanDate] = useState(new Date().toISOString().slice(0, 10));
  const [scanTag, setScanTag] = useState("");
  const [toast, setToast] = useState("");
  const [cameraDebug, setCameraDebug] = useState("");
  const [tapToPlayHint, setTapToPlayHint] = useState(false);
  const [popupTag, setPopupTag] = useState(null); // { tag, color }
  const [flashRow, setFlashRow] = useState(null);
  const [showManual, setShowManual] = useState(false);
  const [manualOrder, setManualOrder] = useState("");
  const [manualTag, setManualTag] = useState("");
  const [manualStatus, setManualStatus] = useState("");
  const [manualStore, setManualStore] = useState("");
  const [fulfilledCounts, setFulfilledCounts] = useState({});
  const [searchText, setSearchText] = useState("");
  function parseServerTs(ts) {
    const s = String(ts || "");
    // If the server datetime is naive (no timezone), assume UTC by appending 'Z'
    const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(s);
    return new Date(hasTz ? s : s + "Z");
  }

  const [loadingCounts, setLoadingCounts] = useState(false);
  const [confirmDup, setConfirmDup] = useState({ show: false, barcode: "", reason: "", message: "" });
  const processingPendingRef = useRef(false);
  const [editTag, setEditTag] = useState(null); // { scan_id, order, currentTag, nextTag }

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
    const storedReturns = localStorage.getItem("returnOrders");
    if (storedReturns) {
      try {
        const list = JSON.parse(storedReturns);
        const today = new Date().toISOString().slice(0, 10);
        setReturnOrders(list.filter((o) => o.ts && o.ts.startsWith(today)));
      } catch {}
    }
  }, []);

  useEffect(() => {
    localStorage.setItem("orders", JSON.stringify(orders));
  }, [orders]);

  useEffect(() => {
    localStorage.setItem("returnOrders", JSON.stringify(returnOrders));
  }, [returnOrders]);

  useEffect(() => {
    if (page === "return" && returnTab === "list") {
      fetchReturnScans();
    }
  }, [page, returnTab, returnDateStart, returnDateEnd]);

  useEffect(() => {
    if (tab === "list") {
      fetchScans();
    }
    if (tab === "fulfilled") {
      fetchFulfilledCounts();
    }
  }, [tab, scanDate, scanTag]);

  // Allow direct links like /return-scan and browser back/forward.
  useEffect(() => {
    const onPop = () => setPage(pageFromPathname(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function goToOrderPage() {
    if (window.location.pathname !== "/") {
      window.history.pushState({}, "", "/");
    }
    setPage("order");
  }

  function goToReturnPage() {
    if (window.location.pathname !== "/return-scan") {
      window.history.pushState({}, "", "/return-scan");
    }
    setPage("return");
  }

  function navigateOrderTab(nextTab) {
    setTab(nextTab);
  }

  // If we switch pages/tabs while the camera is running, stop and clear the scanner to avoid
  // stale DOM references (the reader element is unmounted/remounted).
  useEffect(() => {
    const qr = scannerRef.current;
    if (!qr) return;
    (async () => {
      try {
        if (qr.isScanning) {
          await qr.stop();
        }
      } catch {}
      try {
        qr.clear();
      } catch {}
      scannerRef.current = null;
      setScanning(false);
      setReturnScanning(false);
      setShowStart(true);
      setShowAgain(false);
      setReturnShowStart(true);
      setReturnShowAgain(false);
    })();
  }, [page, tab, returnTab]);

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
    setCameraDebug("");
    setTapToPlayHint(false);
    setToast("Starting camera...");
    setTimeout(() => setToast(""), 1200);

    let qr = scannerRef.current;
    const ios = isIOS();
    const config = {
      fps: ios ? 12 : 25,
      qrbox: (vw, vh) => {
        // Use a larger scan area. Since the container is wide and short, 
        // we want to use most of the height.
        // We'll use a rectangular box that fits well.
        return { width: vw * 0.8, height: vh * 0.8 };
      },
      // iOS BarcodeDetector support is inconsistent for 1D barcodes (e.g. CODE_128).
      // Prefer the JS decoder on iPhone/iPad for reliability.
      experimentalFeatures: { useBarCodeDetectorIfSupported: !ios },
      // Explicit formats help reliability and performance, especially on iOS.
      formatsToSupport: [
        Html5QrcodeSupportedFormats.CODE_128,
        Html5QrcodeSupportedFormats.CODE_39,
        Html5QrcodeSupportedFormats.EAN_13,
        Html5QrcodeSupportedFormats.EAN_8,
        Html5QrcodeSupportedFormats.UPC_A,
        Html5QrcodeSupportedFormats.UPC_E,
        Html5QrcodeSupportedFormats.ITF,
        Html5QrcodeSupportedFormats.QR_CODE,
        Html5QrcodeSupportedFormats.PDF_417,
      ],
      disableFlip: true,
      aspectRatio: 1.0,
    };
    const onScan = (code) => {
      const now = Date.now();
      const last = recentCodesRef.current.get(code) || 0;
      // Ignore repeated reads of the same code within 2 seconds
      if (now - last < 2000) return;
      recentCodesRef.current.set(code, now);

      if (navigator.vibrate) navigator.vibrate(60);
      setResult("⏳ Processing scan...");
      
      // Stop scanning immediately
      if (scannerRef.current) {
         scannerRef.current.stop().then(() => {
             setScanning(false);
             setShowAgain(true);
         }).catch(() => {
             setScanning(false);
             setShowAgain(true);
         });
      } else {
          setScanning(false);
          setShowAgain(true);
      }

      // Show instantly in the list
      addOrderToList({ result: "⏳ Processing", order: code, tag: "", ts: new Date().toISOString() });
      processScan(code);
    };

    const handleStartError = (err) => {
      if (qr) {
        qr.stop().catch(() => {});
        qr.clear();
      }
      const isHttps = window.location.protocol === "https:" || window.location.hostname === "localhost";
      const errMsg = err ? String(err) : "";
      const msg = isHttps
        ? `Camera failed to start${errMsg ? `: ${errMsg}` : ""}`
        : "Camera requires HTTPS on iPhone Safari (open via https://)";
      handleScanError(msg);
      setCameraDebug(msg);
      setScanning(false);
      setShowStart(true);
    };

    const applyIosVideoAttrs = () => {
      const root = readerRef.current;
      if (!root) return;
      const vid = root.querySelector("video");
      if (!vid) return;
      // iPhone Safari needs inline playback for camera video
      vid.setAttribute("playsinline", "true");
      vid.setAttribute("webkit-playsinline", "true");
      vid.setAttribute("autoplay", "true");
      vid.setAttribute("muted", "true");
      // Some iOS versions require the property, not only the attribute
      try {
        vid.playsInline = true;
      } catch {}
      vid.muted = true;
      vid.autoplay = true;
      // Try to kick video playback; ignore failures
      vid.play?.().catch?.(() => {});
    };

    const tryPlayPreviewVideo = () => {
      const root = readerRef.current;
      if (!root) return false;
      const vid = root.querySelector("video");
      if (!vid) return false;
      applyIosVideoAttrs();
      try {
        const p = vid.play?.();
        if (p?.catch) p.catch(() => {});
      } catch {}
      return true;
    };

    const verifyVideo = () => {
      const startedAt = Date.now();
      const tick = () => {
        const root = readerRef.current;
        if (!root) return;
        const vid = root.querySelector("video");
        applyIosVideoAttrs();
        // If the element exists but is still paused/black, hint user to tap to start playback.
        if (vid && (vid.paused || vid.readyState < 2)) {
          setTapToPlayHint(true);
        }
        // On iOS, videoWidth/Height can remain 0 for a moment even when stream is OK.
        // Also, some implementations don't expose srcObject reliably—use multiple signals.
        const ok =
          !!vid &&
          (vid.readyState >= 2 ||
            (vid.srcObject && vid.srcObject.getTracks && vid.srcObject.getTracks().length > 0) ||
            vid.currentTime > 0);
        if (ok) {
          setTapToPlayHint(false);
          return;
        }
        // Don't hard-fail too aggressively; just keep trying for a bit longer.
        if (Date.now() - startedAt > 2500) {
          // Try an explicit play attempt; if still not ok, keep the tap hint visible.
          tryPlayPreviewVideo();
        }
        if (Date.now() - startedAt > 8000) {
          setCameraDebug("Camera started but preview is not playing. Tap inside the camera box once.");
          return;
        }
        setTimeout(tick, 250);
      };
      setTimeout(tick, 250);
    };

    const startNew = () => {
      const startWith = (camera) =>
        qr
          .start(camera, config, onScan, () => {})
          .then(() => {
            hideLibraryInfo();
            applyIosVideoAttrs();
            verifyVideo();
          });

      // Prefer environment camera; if iOS/Safari is picky, fall back to an explicit cameraId
      // 1) Most compatible form across browsers/libs
      startWith({ facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } })
        .catch(async () => {
          try {
            // 2) Some browsers prefer the "ideal" constraint form
            await startWith({ facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } });
            return;
          } catch {}
          try {
            const cams = await Html5Qrcode.getCameras();
            const back =
              [...(cams || [])].reverse().find((c) => /back|rear|environment/i.test(c.label || "")) ||
              (cams || [])[cams.length - 1];
            if (back?.id) {
              return startWith(back.id);
            }
          } catch {}
          throw new Error("start_failed");
        })
        .catch(handleStartError);
    };

    if (!qr) {
      qr = new Html5Qrcode(readerRef.current.id);
      scannerRef.current = qr;
      startNew();
    } else {
      // Try to recover state
      try {
        if (qr.isScanning) {
           return;
        }
        startNew();
      } catch (e) {
         // If error checking state, just try to start
         startNew();
      }
    }
  }

  function startReturnScanner() {
    setReturnResult("");
    setReturnResultClass("");
    setReturnScanning(true);
    setReturnShowStart(false);
    setReturnShowAgain(false);
    setCameraDebug("");
    setTapToPlayHint(false);
    setToast("Starting camera...");
    setTimeout(() => setToast(""), 1200);

    let qr = scannerRef.current;
    const ios = isIOS();
    const config = {
      fps: ios ? 12 : 25,
      qrbox: (vw, vh) => {
        return { width: vw * 0.8, height: vh * 0.8 };
      },
      experimentalFeatures: { useBarCodeDetectorIfSupported: !ios },
      formatsToSupport: [
        Html5QrcodeSupportedFormats.CODE_128,
        Html5QrcodeSupportedFormats.CODE_39,
        Html5QrcodeSupportedFormats.EAN_13,
        Html5QrcodeSupportedFormats.EAN_8,
        Html5QrcodeSupportedFormats.UPC_A,
        Html5QrcodeSupportedFormats.UPC_E,
        Html5QrcodeSupportedFormats.ITF,
        Html5QrcodeSupportedFormats.QR_CODE,
        Html5QrcodeSupportedFormats.PDF_417,
      ],
      disableFlip: true,
      aspectRatio: 1.0,
    };

    const onScan = (code) => {
      const now = Date.now();
      const last = recentCodesRef.current.get(code) || 0;
      if (now - last < 2000) return;
      recentCodesRef.current.set(code, now);

      if (navigator.vibrate) navigator.vibrate(60);
      setReturnResult("⏳ Processing scan...");

      if (scannerRef.current) {
        scannerRef.current
          .stop()
          .then(() => {
            setReturnScanning(false);
            setReturnShowAgain(true);
          })
          .catch(() => {
            setReturnScanning(false);
            setReturnShowAgain(true);
          });
      } else {
        setReturnScanning(false);
        setReturnShowAgain(true);
      }

      addReturnOrderToList({
        result: "⏳ Processing",
        order: code,
        store: "",
        fulfillment: "",
        status: "",
        financial: "",
        ts: new Date().toISOString(),
      });
      processReturnScan(code);
    };

    const handleStartError = (err) => {
      if (qr) {
        qr.stop().catch(() => {});
        qr.clear();
      }
      const isHttps = window.location.protocol === "https:" || window.location.hostname === "localhost";
      const errMsg = err ? String(err) : "";
      const msg = isHttps
        ? `Camera failed to start${errMsg ? `: ${errMsg}` : ""}`
        : "Camera requires HTTPS on iPhone Safari (open via https://)";
      setReturnResult(`❌ Error: ${msg}`);
      setReturnResultClass("result-error");
      playErrorSound();
      setCameraDebug(msg);
      setReturnScanning(false);
      setReturnShowStart(true);
    };

    const applyIosVideoAttrs = () => {
      const root = readerRef.current;
      if (!root) return;
      const vid = root.querySelector("video");
      if (!vid) return;
      vid.setAttribute("playsinline", "true");
      vid.setAttribute("webkit-playsinline", "true");
      vid.setAttribute("autoplay", "true");
      vid.setAttribute("muted", "true");
      try {
        vid.playsInline = true;
      } catch {}
      vid.muted = true;
      vid.autoplay = true;
      vid.play?.().catch?.(() => {});
    };

    const tryPlayPreviewVideo = () => {
      const root = readerRef.current;
      if (!root) return false;
      const vid = root.querySelector("video");
      if (!vid) return false;
      applyIosVideoAttrs();
      try {
        const p = vid.play?.();
        if (p?.catch) p.catch(() => {});
      } catch {}
      return true;
    };

    const verifyVideo = () => {
      const startedAt = Date.now();
      const tick = () => {
        const root = readerRef.current;
        if (!root) return;
        const vid = root.querySelector("video");
        applyIosVideoAttrs();
        if (vid && (vid.paused || vid.readyState < 2)) {
          setTapToPlayHint(true);
        }
        const ok =
          !!vid &&
          (vid.readyState >= 2 ||
            (vid.srcObject && vid.srcObject.getTracks && vid.srcObject.getTracks().length > 0) ||
            vid.currentTime > 0);
        if (ok) {
          setTapToPlayHint(false);
          return;
        }
        if (Date.now() - startedAt > 2500) {
          tryPlayPreviewVideo();
        }
        if (Date.now() - startedAt > 8000) {
          setCameraDebug("Camera started but preview is not playing. Tap inside the camera box once.");
          return;
        }
        setTimeout(tick, 250);
      };
      setTimeout(tick, 250);
    };

    const startNew = () => {
      const startWith = (camera) =>
        qr
          .start(camera, config, onScan, () => {})
          .then(() => {
            hideLibraryInfo();
            applyIosVideoAttrs();
            verifyVideo();
          });

      startWith({ facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } })
        .catch(async () => {
          try {
            await startWith({ facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } });
            return;
          } catch {}
          try {
            const cams = await Html5Qrcode.getCameras();
            const back =
              [...(cams || [])].reverse().find((c) => /back|rear|environment/i.test(c.label || "")) ||
              (cams || [])[cams.length - 1];
            if (back?.id) {
              return startWith(back.id);
            }
          } catch {}
          throw new Error("start_failed");
        })
        .catch(handleStartError);
    };

    if (!qr) {
      qr = new Html5Qrcode(readerRef.current.id);
      scannerRef.current = qr;
      startNew();
    } else {
      try {
        if (qr.isScanning) {
          return;
        }
        startNew();
      } catch {
        startNew();
      }
    }
  }

  function getPendingQueue() {
    try {
      return JSON.parse(localStorage.getItem("pendingScans") || "[]");
    } catch {
      return [];
    }
  }
  function setPendingQueue(q) {
    localStorage.setItem("pendingScans", JSON.stringify(q));
  }
  function enqueuePending(barcode) {
    const q = getPendingQueue();
    q.push({ barcode, ts: Date.now() });
    setPendingQueue(q);
  }

  async function processScan(barcode, opts = { confirm_duplicate: false }) {
    try {
      const resp = await fetch(`${apiBase}/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ barcode, confirm_duplicate: !!opts.confirm_duplicate }),
      });
      const data = await resp.json();
      if (data.needs_confirmation) {
        setResult(`${statusIcon(data.result)} ${data.result}`);
        setResultClass("result-warning");
        setConfirmDup({ show: true, barcode, reason: data.reason || "", message: data.result });
        setShowAgain(false);
        return;
      }
      updateScanUI(data);
    } catch (e) {
      enqueuePending(barcode);
      // Don't show toast for automatic retries to avoid spam
      // setToast("Saved to retry \u21bb");
      // setTimeout(() => setToast(""), 1200);
    }
  }

  async function processReturnScan(barcode) {
    try {
      const resp = await fetch(`${apiBase}/return-scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ barcode }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        const msg = data?.detail || "Return scan failed";
        setReturnResult(`❌ Error: ${msg}`);
        setReturnResultClass("result-error");
        playErrorSound();
        return;
      }
      updateReturnScanUI(data);
    } catch (e) {
      setReturnResult("❌ Error: Network error");
      setReturnResultClass("result-error");
      playErrorSound();
    }
  }

  useEffect(() => {
    const run = async () => {
      if (processingPendingRef.current) return;
      const q = getPendingQueue();
      if (!q.length) return;
      processingPendingRef.current = true;
      try {
        const next = q.shift();
        setPendingQueue(q);
        await processScan(next.barcode);
      } finally {
        processingPendingRef.current = false;
      }
    };
    const id = setInterval(run, 2000);
    return () => clearInterval(id);
  }, []);


  function handleScanError(msg) {
    setResult(`❌ Error: ${msg}`);
    setResultClass("result-error");
    playErrorSound();
  }

  function updateScanUI(data) {
    const { result: res, order, tag, ts, scan_id } = data;
    setResult(`${statusIcon(res)} ${res}`);
    setResultClass(resultClassFrom(res));
    if (res.includes("✅")) {
      playSuccessSound();
      if (tag) {
        setPopupTag({ tag, color: tagColors[(tag || "none").toLowerCase()] || tagColors["none"] });
        setTimeout(() => setPopupTag(null), 1500);
      }
      // Trigger summary update logic more explicitly for animation
      fetchSummary();
    } else {
      playErrorSound();
    }
    // Replace the placeholder if present, otherwise prepend
    setOrders((prev) => {
      if (prev.length && (prev[0].result || "").startsWith("⏳")) {
        const [_first, ...rest] = prev;
        return [{ result: res, order, tag, ts, scan_id }, ...rest].slice(0, 20);
      }
      return [{ result: res, order, tag, ts, scan_id }, ...prev].slice(0, 20);
    });
    if (res.includes("Duplicate phone")) {
      setToast("⚠️ Duplicate phone in last 3 days");
      setTimeout(() => setToast(""), 2000);
    }
    fetchSummary();
  }

  function updateReturnScanUI(data) {
    const { result: res, order, store, fulfillment, status, financial, ts } = data;
    setReturnResult(`${statusIcon(res)} ${res}`);
    setReturnResultClass(resultClassFrom(res));
    if (res.includes("✅")) {
      playSuccessSound();
    } else {
      playErrorSound();
    }

    setReturnOrders((prev) => {
      if (prev.length && (prev[0].result || "").startsWith("⏳")) {
        const [_first, ...rest] = prev;
        return [{ result: res, order, store, fulfillment, status, financial, ts }, ...rest].slice(0, 20);
      }
      return [{ result: res, order, store, fulfillment, status, financial, ts }, ...prev].slice(0, 20);
    });
  }

  function addOrderToList(item) {
    setOrders((prev) => [item, ...prev].slice(0, 20));
  }

  function addReturnOrderToList(item) {
    setReturnOrders((prev) => [item, ...prev].slice(0, 20));
  }

  async function updateDeliveryTagFromScanList(scan_id, nextTag) {
    const res = await fetch(`${apiBase}/scans/${scan_id}/delivery-tag`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: nextTag }),
    });
    if (!res.ok) {
      setToast("Tag update failed");
      setTimeout(() => setToast(""), 1500);
      return null;
    }
    const row = await res.json();
    return row;
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

  async function fetchReturnScans() {
    const start = returnDateStart;
    const end = returnDateEnd || returnDateStart;
    const url = new URL(`${apiBase}/return-scans`, window.location.origin);
    url.searchParams.set("start", start);
    url.searchParams.set("end", end);
    const res = await fetch(url.toString());
    const data = await res.json();
    setReturnRows(Array.isArray(data) ? data : []);
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

  async function createManualScan() {
    if (!manualOrder.trim()) return;
    const payload = {
      order_name: manualOrder.trim(),
      tags: manualTag,
      status: manualStatus,
      store: manualStore,
    };
    const res = await fetch(`${apiBase}/scans`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      setShowManual(false);
      setManualOrder("");
      setManualTag("");
      setManualStatus("");
      setManualStore("");
      setToast("Added manually \u2713");
      setTimeout(() => setToast(""), 1500);
      fetchScans();
      fetchSummary();
    }
  }

  async function fetchFulfilledCounts() {
    try {
      setLoadingCounts(true);
      const url = new URL(`${apiBase}/fulfilled-counts`, window.location.origin);
      url.searchParams.set("date", scanDate);
      const res = await fetch(url.toString());
      const data = await res.json();
      setFulfilledCounts(data || {});
    } finally {
      setLoadingCounts(false);
    }
  }

  const displayedOrders = orders;

  const listTagCounts = {};
  scanRows.forEach((r) => {
    const t = detectTag(r.tags);
    listTagCounts[t] = (listTagCounts[t] || 0) + 1;
  });

  function digitsOnly(str) {
    return (str || "").replace(/\D+/g, "");
  }

  function normalizePhoneDigits(str) {
    let d = digitsOnly(str);
    if (d.startsWith("212")) d = d.slice(3);
    while (d.startsWith("0")) d = d.slice(1);
    return d;
  }

  function normalizeOrderDigits(str) {
    return digitsOnly(str);
  }

  function matchesSearch(row) {
    const qRaw = (searchText || "").trim();
    if (!qRaw) return true;
    const q = qRaw.toLowerCase();

    // Text match on order name
    if ((row.order_name || "").toLowerCase().includes(q)) return true;

    // Digit-based matching for orders and phones
    const qDigits = digitsOnly(qRaw);
    if (qDigits) {
      const orderDigits = normalizeOrderDigits(row.order_name);
      if (orderDigits.includes(qDigits)) return true;

      const rowPhoneNorm = normalizePhoneDigits(row.phone || "");
      const qPhoneNorm = normalizePhoneDigits(qDigits);
      if (qPhoneNorm) {
        if (rowPhoneNorm.includes(qPhoneNorm) || qPhoneNorm.includes(rowPhoneNorm)) return true;
      }
    }

    return false;
  }

  const filteredBySearch = scanRows.filter((r) => matchesSearch(r));
  const displayedList = scanTag
    ? filteredBySearch.filter((r) => detectTag(r.tags) === scanTag)
    : filteredBySearch;

  return (
    <div className="container">
      {page === "order" && (
        <div className="tab-bar">
          <button className={tab === "scan" ? "active" : ""} onClick={() => navigateOrderTab("scan")}>
            Scan
          </button>
          <button className={tab === "list" ? "active" : ""} onClick={() => navigateOrderTab("list")}>
            Scanned Orders
          </button>
          <button className={tab === "fulfilled" ? "active" : ""} onClick={() => navigateOrderTab("fulfilled")}>
            Shopify Fulfilled
          </button>
          <button className="" onClick={goToReturnPage}>
            Return Scanner
          </button>
        </div>
      )}

      {page === "return" && (
        <div className="tab-bar">
          <button className={returnTab === "scan" ? "active" : ""} onClick={() => setReturnTab("scan")}>
            Scan Return
          </button>
          <button className={returnTab === "list" ? "active" : ""} onClick={() => setReturnTab("list")}>
            Scanned Returns{returnTab === "list" ? ` (${returnRows.length})` : ""}
          </button>
          <button className="" onClick={goToOrderPage}>
            Order Scanner
          </button>
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
      {!!cameraDebug && (
        <div style={{ color: "#111827", background: "rgba(255,255,255,0.9)", padding: "0.4rem 0.6rem", borderRadius: 10, marginBottom: "0.5rem", fontSize: "0.9rem" }}>
          <strong>Camera:</strong> {cameraDebug}
        </div>
      )}
      {page === "order" && tab === "scan" && (
        <>
          <div className="header">
            <h1>📦 Order Scanner</h1>
            <div
              id="reader"
              ref={readerRef}
              className={scanning ? "scanning" : ""}
              onClick={() => {
                // Some mobile browsers block autoplay until an explicit user gesture.
                const vid = readerRef.current?.querySelector?.("video");
                if (vid) {
                  try {
                    vid.play?.().catch?.(() => {});
                  } catch {}
                }
              }}
            ></div>
            {tapToPlayHint && (
              <div style={{ marginTop: 6, color: "#6b7280", fontSize: "0.9rem" }}>
                If the camera is white/blank: <strong>tap inside the camera box once</strong>.
              </div>
            )}
            {popupTag && (
              <div
                className="tag-popup"
                style={{ backgroundColor: popupTag.color }}
              >
                {popupTag.tag.toUpperCase()}
              </div>
            )}
            {result && (
              <div id="result" className={resultClass}>
                {result}
              </div>
            )}
          </div>
          <div id="scan-log">
            <ul id="orderList">
              {displayedOrders.map((o, i) => {
                const tColor = tagColors[(o.tag || "none").toLowerCase()] || tagColors["none"];
                return (
                  <li
                    key={i}
                    className={`order-item ${statusClass(o.result)}`}
                    style={{
                      borderLeftColor: tColor,
                      background: `linear-gradient(90deg, ${tColor}22 0%, transparent 100%)`
                    }}
                  >
                    <span className="order-name">{o.order}</span>
                    <span
                      className="order-tag"
                      style={{ background: tColor }}
                      title="Click to change delivery tag"
                      onClick={() => {
                        if (!o.scan_id) {
                          setToast("Can't edit this item yet (missing scan id). Scan again.");
                          setTimeout(() => setToast(""), 2000);
                          return;
                        }
                        const current = (o.tag || "").toLowerCase();
                        setEditTag({ scan_id: o.scan_id, order: o.order, currentTag: current, nextTag: current || "" });
                      }}
                    >
                      {o.tag || "No tag"}
                    </span>
                    <span className="order-status-text">{o.result}</span>
                  </li>
                );
              })}
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
      {page === "return" && returnTab === "scan" && (
        <>
          <div className="header">
            <h1>↩️ Return Scanner</h1>
            <div
              id="reader"
              ref={readerRef}
              className={returnScanning ? "scanning" : ""}
              onClick={() => {
                const vid = readerRef.current?.querySelector?.("video");
                if (vid) {
                  try {
                    vid.play?.().catch?.(() => {});
                  } catch {}
                }
              }}
            ></div>
            {tapToPlayHint && (
              <div style={{ marginTop: 6, color: "#6b7280", fontSize: "0.9rem" }}>
                If the camera is white/blank: <strong>tap inside the camera box once</strong>.
              </div>
            )}
            {returnResult && (
              <div id="result" className={returnResultClass}>
                {returnResult}
              </div>
            )}
          </div>
          <div className="bottom-bar">
            {returnShowStart && (
              <button className="scan-btn" id="scanBtnReturn" onClick={startReturnScanner}>
                <span className="emoji">📷</span>Scan
              </button>
            )}
            {returnShowAgain && (
              <button className="scan-btn" id="againBtnReturn" onClick={startReturnScanner}>
                <span className="emoji">🔄</span>Scan Again
              </button>
            )}
          </div>
        </>
      )}
      {page === "return" && returnTab === "list" && (
        <div className="table-card">
          <div className="filters" style={{ justifyContent: "space-between" }}>
            <div className="filters" style={{ marginBottom: 0 }}>
              <input
                type="date"
                value={returnDateStart}
                onChange={(e) => setReturnDateStart(e.target.value)}
              />
              <input
                type="date"
                value={returnDateEnd}
                onChange={(e) => setReturnDateEnd(e.target.value)}
                placeholder="End date"
              />
              <button className="btn" onClick={fetchReturnScans}>
                🔄 Refresh
              </button>
            </div>
            <div style={{ fontWeight: 700 }}>Returns: {returnRows.length}</div>
          </div>
          <table className="scans-table">
            <thead>
              <tr>
                <th>Order #</th>
                <th>Store</th>
                <th>Fulfillment</th>
                <th>Financial</th>
                <th>Status</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {returnRows.map((o, i) => (
                <tr key={i}>
                  <td><strong>{o.order_name || o.order}</strong></td>
                  <td>{(o.store || "").toUpperCase()}</td>
                  <td>{o.fulfillment || ""}</td>
                  <td>{o.financial || ""}</td>
                  <td>{o.status || ""}</td>
                  <td>{o.result || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {page === "order" && tab === "list" && (
        <div className="table-card">
          <div className="filters">
            <input
              type="date"
              value={scanDate}
              onChange={(e) => setScanDate(e.target.value)}
            />
            <input
              type="text"
              placeholder="Search by order or phone"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
            />
            <button className="btn" onClick={() => setShowManual(true)}>➕ Add Manually</button>
            <div className="tag-pills">
              <span
                className={`tag-pill ${scanTag === "" ? "active" : ""}`}
                onClick={() => setScanTag("")}
              >
                All ({scanRows.length})
              </span>
              {Object.entries(listTagCounts)
                .filter(([tag]) => tag !== "big")
                .map(([tag, count]) => (
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
              {!!scanTag && (
                <button
                  className="btn"
                  title="Generate PDF of order numbers and timestamps"
                  onClick={() => {
                    try {
                      const doc = new jsPDF();
                      const title = `Orders ${scanDate}${scanTag ? ` - ${scanTag.toUpperCase()}` : ""}`;
                      doc.setFontSize(16);
                      doc.text(title, 14, 18);
                      doc.setFontSize(12);
                      let y = 28;
                      doc.text("Order #", 14, y);
                      doc.text("Timestamp", 100, y);
                      y += 6;
                      displayedList.forEach((r) => {
                        if (y > 280) {
                          doc.addPage();
                          y = 20;
                        }
                        const ts = parseServerTs(r.ts).toLocaleString();
                        doc.text(String(r.order_name || ""), 14, y);
                        doc.text(ts, 100, y);
                        y += 6;
                      });
                      const filename = `orders_${scanDate}${scanTag ? `_${scanTag}` : ""}.pdf`;
                      doc.save(filename);
                    } catch (e) {
                      setToast("PDF generation failed");
                      setTimeout(() => setToast(""), 1500);
                    }
                  }}
                  style={{ marginLeft: 8 }}
                >
                  🖨️ Generate PDF
                </button>
              )}
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
                  <td>{parseServerTs(r.ts).toLocaleTimeString()}</td>
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
      {page === "order" && tab === "fulfilled" && (
        <div className="table-card">
          <div className="filters">
            <input
              type="date"
              value={scanDate}
              onChange={(e) => setScanDate(e.target.value)}
            />
            <button className="btn" onClick={fetchFulfilledCounts} disabled={loadingCounts}>
              {loadingCounts ? "Refreshing..." : "🔄 Refresh"}
            </button>
          </div>
          <div className="fulfilled-grid">
            <div className="summary-box" style={{ background:'#c7f9cc' }}>
              <div className="summary-name">IRRANOVA</div>
              <div className="summary-count">{fulfilledCounts["irranova"] || 0}</div>
            </div>
            <div className="summary-box" style={{ background:'#bde0fe' }}>
              <div className="summary-name">IRRAKIDS</div>
              <div className="summary-count">{fulfilledCounts["irrakids"] || 0}</div>
            </div>
          </div>
        </div>
      )}
      {confirmDup.show && (
        <div className="modal-overlay" onClick={() => setConfirmDup({ show:false, barcode:"", reason:"", message:"" })}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Duplicate detected</h3>
            <p style={{marginTop:0}}>{confirmDup.message}</p>
            <div className="modal-actions">
              <button className="btn btn-danger" onClick={() => {
                // Remove pending placeholder if present
                setOrders((prev) => {
                  if (prev.length && (prev[0].result || '').startsWith('⏳') && prev[0].order === confirmDup.barcode) {
                    return prev.slice(1);
                  }
                  return prev;
                });
                setConfirmDup({ show:false, barcode:"", reason:"", message:"" });
                setResult("❌ Rejected");
                setResultClass("result-error");
              }}>Reject</button>
              <button className="btn btn-primary" onClick={async () => {
                const code = confirmDup.barcode;
                setConfirmDup({ show:false, barcode:"", reason:"", message:"" });
                await processScan(code, { confirm_duplicate: true });
              }}>Accept</button>
            </div>
          </div>
        </div>
      )}
      {showManual && (
        <div className="modal-overlay" onClick={() => setShowManual(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Add Scan Manually</h3>
            <div className="form-row">
              <label>Order #</label>
              <input placeholder="#123456" value={manualOrder} onChange={(e)=>setManualOrder(e.target.value)} />
            </div>
            <div className="form-row">
              <label>Tag</label>
              <select value={manualTag} onChange={(e)=>setManualTag(e.target.value)}>
                <option value="">None</option>
                {Object.keys(tagColors).map((t)=>(
                  <option key={t} value={t}>{t.toUpperCase()}</option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label>Status</label>
              <select value={manualStatus} onChange={(e)=>setManualStatus(e.target.value)}>
                <option value="">—</option>
                <option>Fulfilled</option>
                <option>Unfulfilled</option>
              </select>
            </div>
            <div className="form-row">
              <label>Store</label>
              <select value={manualStore} onChange={(e)=>setManualStore(e.target.value)}>
                <option value="">—</option>
                <option value="irranova">Irranova</option>
                <option value="irrakids">Irrakids</option>
              </select>
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowManual(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={createManualScan}>Add</button>
            </div>
          </div>
        </div>
      )}
      {editTag && (
        <div className="modal-overlay" onClick={() => setEditTag(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Change delivery tag</h3>
            <p style={{ marginTop: 0, color: "#374151" }}>
              Order: <strong>{editTag.order}</strong>
            </p>
            <div className="form-row">
              <label>Tag</label>
              <select
                value={editTag.nextTag}
                onChange={(e) => setEditTag((cur) => ({ ...cur, nextTag: e.target.value }))}
              >
                <option value="">None</option>
                {Object.keys(tagColors)
                  .filter((t) => t !== "none")
                  .map((t) => (
                    <option key={t} value={t}>
                      {t.toUpperCase()}
                    </option>
                  ))}
              </select>
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setEditTag(null)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={async () => {
                  const scanId = editTag.scan_id;
                  const nextTag = (editTag.nextTag || "").toLowerCase();
                  const updated = await updateDeliveryTagFromScanList(scanId, nextTag);
                  if (updated) {
                    const canonical = detectTag(updated.tags) || "";
                    setOrders((prev) =>
                      prev.map((x) => (x.scan_id === scanId ? { ...x, tag: canonical || "" } : x))
                    );
                    setToast("Tag updated ✓");
                    setTimeout(() => setToast(""), 1200);
                    fetchSummary();
                    setEditTag(null);
                  }
                }}
              >
                Approve
              </button>
            </div>
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
