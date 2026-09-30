import React, { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Room, RoomEvent, Track } from 'livekit-client';
import { agentsApi, api, callExportUrl, playgroundApi } from '../api.js';
import LatencyPanel from '../components/LatencyPanel.jsx';
import DiagnosticsPanel from '../components/DiagnosticsPanel.jsx';
import LiveConsole from '../components/LiveConsole.jsx';
import TestCallPanel from '../components/TestCallPanel.jsx';
import LeadCardForm, { ABSENT_STUDENT_DEFAULTS } from '../components/LeadCardForm.jsx';
import TextPlayground, { confidenceClass } from '../components/TextPlayground.jsx';
import { cleanTranscriptText } from '../utils/transcript.js';


const PHASES = {
  SETUP: 'setup',
  CONNECTING: 'connecting',
  IN_CALL: 'in_call',
  ENDED: 'ended',
  TEXT: 'text',
};

const MODES = {
  VOICE: 'voice',
  TEXT: 'text',
};

const MIC_SPEAK_THRESHOLD = 0.12;
const BARGE_DECAY_MS = 650;

function fmtClock(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// Reads the ACTUAL published microphone state. Used to separate "the browser
// is not sending audio" from "Deepgram is not transcribing it" - the two look
// identical from the agent side and have completely different fixes.
export function readMicDiagnostic(pub) {
  if (!pub) {
    return {
      published: false,
      error: 'no microphone track publication - permission denied or no input device',
    };
  }
  const track = pub.audioTrack || pub.track;
  const settings = track?.mediaStreamTrack?.getSettings?.() || {};
  return {
    published: true,
    muted: Boolean(pub.isMuted),
    trackMuted: Boolean(track?.mediaStreamTrack?.enabled === false),
    readyState: track?.mediaStreamTrack?.readyState || null,
    sampleRate: settings.sampleRate ?? null,
    channelCount: settings.channelCount ?? null,
    echoCancellation: settings.echoCancellation ?? null,
    noiseSuppression: settings.noiseSuppression ?? null,
    autoGainControl: settings.autoGainControl ?? null,
    label: track?.mediaStreamTrack?.label || null,
  };
}

export default function PlaygroundPage() {
  const params = useParams();
  const routeVersionId = params.agentVersionId ? Number(params.agentVersionId) : null;

  const [phase, setPhase] = useState(PHASES.SETUP);
  const [mode, setMode] = useState(MODES.VOICE); // voice (mic) | text

  // ---- setup ----
  const [agents, setAgents] = useState(null);
  const [agentsError, setAgentsError] = useState(null);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [versions, setVersions] = useState([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState(routeVersionId || '');
  const [contactCard, setContactCard] = useState({ ...ABSENT_STUDENT_DEFAULTS });
  const [versionInfo, setVersionInfo] = useState(null); // {agentName, version}
  const [infoError, setInfoError] = useState(null);
  // Surfaced in the Diagnostics panel so an operator can tell which run an
  // event belongs to.
  const [activeCallId, setActiveCallId] = useState(null);

  // ---- live session (voice mode) ----
  const [connectError, setConnectError] = useState(null);
  const [statusNote, setStatusNote] = useState(null);
  const [fatalError, setFatalError] = useState(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [micLevel, setMicLevel] = useState(0);
  // Mic self-mute + the published-track diagnostic the panel reads.
  const [micMuted, setMicMuted] = useState(false);
  const [micDiag, setMicDiag] = useState(null);
  const [bargeIn, setBargeIn] = useState(false);
  const [captions, setCaptions] = useState([]);

  // ---- post-call ----
  // Text-mode session state lives inside <TextPlayground>; the page only
  // keeps the finished report for the ENDED view.
  const [result, setResult] = useState(null);
  const [completeError, setCompleteError] = useState(null);
  const [completing, setCompleting] = useState(false);

  // refs (mutable values not rendered directly)
  const roomRef = useRef(null);
  const sessionRef = useRef(null);
  const micTrackRef = useRef(null);
  const timerRef = useRef(null);
  const levelTimerRef = useRef(null);
  const statusTimerRef = useRef(null);
  const startedAtRef = useRef(0);
  const userEndedRef = useRef(false);
  const reconnectTriesRef = useRef(0);
  const remotePlayingRef = useRef(false);
  const bargeUntilRef = useRef(0);
  const audioElsRef = useRef([]);

  // ---- load agents for the picker (only when no version in the URL) ----
  useEffect(() => {
    if (routeVersionId) return;
    let cancelled = false;
    setAgentsError(null);
    agentsApi
      .list()
      .then((list) => {
        if (cancelled) return;
        const rows = Array.isArray(list) ? list : [];
        setAgents(rows);
        if (rows.length > 0) setSelectedAgentId((prev) => prev || String(rows[0].id));
      })
      .catch((e) => !cancelled && setAgentsError(e.message || String(e)));
    return () => {
      cancelled = true;
    };
  }, [routeVersionId]);

  // ---- load version list when the picked agent changes ----
  useEffect(() => {
    if (routeVersionId || !selectedAgentId) return;
    let cancelled = false;
    setVersionsLoading(true);
    agentsApi
      .listVersions(selectedAgentId)
      .then((list) => {
        if (cancelled) return;
        const rows = Array.isArray(list) ? list.slice().reverse() : [];
        setVersions(rows);
        setSelectedVersionId((prev) => {
          if (prev && rows.some((v) => String(v.id) === String(prev))) return prev;
          return rows.length ? String(rows[0].id) : '';
        });
      })
      .catch(() => {
        if (!cancelled) setVersions([]);
      })
      .finally(() => !cancelled && setVersionsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [routeVersionId, selectedAgentId]);

  // ---- resolve header info for whichever version is active ----
  useEffect(() => {
    if (!selectedVersionId) {
      setVersionInfo(null);
      return;
    }
    let cancelled = false;
    setInfoError(null);
    agentsApi
      .getVersion(selectedVersionId)
      .then(async (v) => {
        if (cancelled) return;
        let agentName = '';
        try {
          const a = await agentsApi.get(v.agent_id);
          agentName = a.name;
        } catch {
          /* header still renders without the agent name */
        }
        setVersionInfo({ agentName, version: v.version });
      })
      .catch((e) => !cancelled && setInfoError(e.message || String(e)));
    return () => {
      cancelled = true;
    };
  }, [selectedVersionId]);

  // ---- teardown on unmount ----
  useEffect(
    () => () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (levelTimerRef.current) clearInterval(levelTimerRef.current);
      if (statusTimerRef.current) clearInterval(statusTimerRef.current);
      try {
        roomRef.current && roomRef.current.disconnect();
      } catch {
        /* already gone */
      }
    },
    []
  );

  function startTimers() {
    if (timerRef.current) clearInterval(timerRef.current);
    if (levelTimerRef.current) clearInterval(levelTimerRef.current);
    if (statusTimerRef.current) clearInterval(statusTimerRef.current);
    startedAtRef.current = Date.now();
    setElapsedMs(0);
    timerRef.current = setInterval(() => setElapsedMs(Date.now() - startedAtRef.current), 500);
    levelTimerRef.current = setInterval(pollMicLevel, 150);
    // Auto-hangup: when the agent ends the call server-side, the room stays
    // open — poll the call status and cut the call (disconnect + results)
    // without the user having to press End call.
    statusTimerRef.current = setInterval(pollCallStatus, 3000);
  }

  async function pollCallStatus() {
    const sess = sessionRef.current;
    if (!sess || !roomRef.current) return;
    try {
      const call = await api.getCall(sess.call_id);
      if (call && call.status === 'completed' && roomRef.current) {
        await endCall();
      }
    } catch {
      /* transient failure — the next poll retries */
    }
  }

  function stopTimers() {
    if (timerRef.current) clearInterval(timerRef.current);
    if (levelTimerRef.current) clearInterval(levelTimerRef.current);
    if (statusTimerRef.current) clearInterval(statusTimerRef.current);
    timerRef.current = null;
    levelTimerRef.current = null;
    statusTimerRef.current = null;
  }

  function pollMicLevel() {
    const track = micTrackRef.current;
    let vol = 0;
    if (track && typeof track.getVolume === 'function') {
      try {
        vol = track.getVolume() || 0;
      } catch {
        vol = 0;
      }
    }
    setMicLevel(vol);
    const now = Date.now();
    if (vol > MIC_SPEAK_THRESHOLD && remotePlayingRef.current) {
      bargeUntilRef.current = now + BARGE_DECAY_MS;
      setBargeIn(true);
    } else if (now > bargeUntilRef.current) {
      setBargeIn(false);
    }
  }

  function attachRemoteAudio(track) {
    const el = document.createElement('audio');
    el.autoplay = true;
    el.style.display = 'none';
    document.body.appendChild(el);
    try {
      track.attach(el);
    } catch {
      el.remove();
      return;
    }
    audioElsRef.current.push({ track, el });
  }

  function detachAllAudio() {
    audioElsRef.current.forEach(({ track, el }) => {
      try {
        track.detach(el);
      } catch {
        /* noop */
      }
      try {
        el.remove();
      } catch {
        /* noop */
      }
    });
    audioElsRef.current = [];
    remotePlayingRef.current = false;
  }

  function handleCaption(payload, participant) {
    let text = '';
    let speaker = '';
    // The worker tags every caption with final:true/false (pipeline.py
    // _publish_caption): partials stream while the caller is still speaking,
    // one final commits the turn. Honor the flag so interim hypotheses update
    // a single live bubble instead of each becoming its own message.
    let final = true;
    try {
      const decoded = new TextDecoder().decode(payload);
      try {
        const obj = JSON.parse(decoded);
        if (obj && typeof obj === 'object' && ('text' in obj || 'type' in obj)) {
          text = String((obj && obj.text) || '');
          speaker = (obj && obj.speaker) || '';
          final = obj.final !== false;
        } else {
          text = typeof obj === 'string' ? obj : decoded;
        }
      } catch {
        text = decoded;
      }
    } catch {
      return;
    }
    const cleanText = cleanTranscriptText(text);
    if (!cleanText) return;
    const who = speaker || (participant && participant.identity) || 'agent';
    setCaptions((prev) => {
      const next = prev.slice(-200);
      const lastIdx = next.length - 1;
      const last = lastIdx >= 0 ? next[lastIdx] : null;
      // Identical repeat of the last committed bubble from the same speaker:
      // never show twice (belt-and-braces against worker double-publish).
      if (last && last.speaker === who && last.committed && last.text === cleanText) {
        return prev;
      }
      // Live interim bubble for this speaker exists: update it in place.
      if (last && last.speaker === who && !last.committed) {
        const updated = next.slice();
        updated[lastIdx] = { ...last, text: cleanText, ts: Date.now(), committed: final };
        return updated;
      }
      return [...next, { speaker: who, text: cleanText, ts: Date.now(), committed: final }].slice(-200);
    });
  }

  async function joinWithSession(sess) {
    const room = new Room({ adaptiveStream: true, dynacast: true });

    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) {
        attachRemoteAudio(track);
        remotePlayingRef.current = true;
      }
    });
    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) {
        audioElsRef.current = audioElsRef.current.filter((a) => a.track !== track);
        if (audioElsRef.current.length === 0) remotePlayingRef.current = false;
      }
    });
    room.on(RoomEvent.DataReceived, handleCaption);
    room.on(RoomEvent.Reconnecting, () => setStatusNote('Connection hiccup — recovering…'));
    room.on(RoomEvent.Reconnected, () => setStatusNote(null));

    // Hard disconnect: either the user hung up or the room dropped. One
    // automatic rejoin is attempted; after that an error card takes over.
    room.on(RoomEvent.Disconnected, () => {
      stopTimers();
      if (userEndedRef.current) return;
      if (reconnectTriesRef.current < 1 && sessionRef.current) {
        reconnectTriesRef.current += 1;
        setStatusNote('Connection lost — automatically rejoining…');
        setTimeout(async () => {
          try {
            await joinWithSession(sessionRef.current);
            setStatusNote(null);
            startTimers();
          } catch (e) {
            setStatusNote(null);
            setFatalError(
              `Lost the connection to the voice room and could not rejoin (${e.message || e}). Nothing you said is lost — press "Back to setup" and start again.`
            );
          }
        }, 900);
      } else {
        setFatalError('The connection to the voice room dropped.');
      }
    });

    await room.connect(sess.livekit_url, sess.livekit_token);
    await room.localParticipant.setMicrophoneEnabled(true);

    const pub = room.localParticipant.getTrackPublication(Track.Source.Microphone);
    micTrackRef.current = pub && pub.audioTrack ? pub.audioTrack : null;

    // Publish the REAL microphone state, not an assumption. "The agent cannot
    // hear me" has two very different causes - the browser is not publishing
    // audio at all (permission/device/processing), or it is publishing and
    // Deepgram is failing. Those are indistinguishable from the agent side, so
    // the panel needs this.
    setMicDiag(readMicDiagnostic(pub));

    roomRef.current = room;
  }

  // Mute/unmute self: the agent must go quiet when the tester stops talking,
  // otherwise its own turn-taking fights the human and both sides talk over
  // each other. Also the quickest check that the agent really does stop
  // reacting to audio.
  async function toggleMute() {
    const room = roomRef.current;
    if (!room) return;
    const next = !micMuted;
    try {
      await room.localParticipant.setMicrophoneEnabled(!next);
      setMicMuted(next);
      const pub = room.localParticipant.getTrackPublication(Track.Source.Microphone);
      setMicDiag(readMicDiagnostic(pub));
    } catch (e) {
      setMicDiag({ error: String(e?.message || e) });
    }
  }

  async function startCall() {
    if (!selectedVersionId) return;
    setPhase(PHASES.CONNECTING);
    setConnectError(null);
    setFatalError(null);
    setResult(null);
    setCompleteError(null);
    setCaptions([]);
    userEndedRef.current = false;
    reconnectTriesRef.current = 0;
    remotePlayingRef.current = false;
    setBargeIn(false);

    // Trigger the browser mic prompt explicitly so a denial surfaces as a
    // clear message instead of a cryptic room error. Echo cancellation,
    // noise suppression, and gain control are requested so the agent's own
    // speech coming out of the speakers is not picked back up — no manual
    // muting/unmuting needed during the call.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      stream.getTracks().forEach((t) => t.stop());
    } catch {
      setConnectError(
        'Microphone access was blocked. Allow microphone permission for this site (check the address-bar icon), then press Start again.'
      );
      setPhase(PHASES.SETUP);
      return;
    }

    let sess;
    try {
      sess = await playgroundApi.startSession(Number(selectedVersionId), contactCard);
      sessionRef.current = sess;
      setActiveCallId(sess.call_id ?? null);
    } catch (e) {
      setConnectError(e.message || 'Could not start a playground session.');
      setPhase(PHASES.SETUP);
      return;
    }

    try {
      await joinWithSession(sess);
      startTimers();
      setPhase(PHASES.IN_CALL);
    } catch (e) {
      setConnectError(e.message || 'Could not join the voice room.');
      try {
        roomRef.current && roomRef.current.disconnect();
      } catch {
        /* noop */
      }
      roomRef.current = null;
      setPhase(PHASES.SETUP);
    }
  }

  async function endCall() {
    userEndedRef.current = true;
    stopTimers();
    try {
      roomRef.current && roomRef.current.disconnect();
    } catch {
      /* noop */
    }
    roomRef.current = null;
    micTrackRef.current = null;
    setPhase(PHASES.ENDED);
    await completeSession();
  }

  async function completeSession() {
    if (!sessionRef.current) return;
    setCompleting(true);
    setCompleteError(null);
    try {
      const res = await playgroundApi.completeSession(sessionRef.current.call_id);
      setResult(res || {});
    } catch (e) {
      setCompleteError(e.message || 'Could not finalize the session.');
    } finally {
      setCompleting(false);
    }
  }

  function backToSetup() {
    stopTimers();
    detachAllAudio();
    sessionRef.current = null;
    micTrackRef.current = null;
    setResult(null);
    setFatalError(null);
    setConnectError(null);
    setStatusNote(null);
    setCaptions([]);
    setElapsedMs(0);
    setBargeIn(false);
    setPhase(PHASES.SETUP);
  }

  // ------------------------------------------------------- text mode handlers
  // The typed-conversation engine (start / turn loop / complete) now lives in
  // components/TextPlayground.jsx — reused here and by the agent workspace.

  // ------------------------------------------------------------------ render

  function renderDiagnosticsSidebar() {
    return (
      <div style={{ marginTop: 18 }}>
        <DiagnosticsPanel active={phase !== PHASES.IDLE} callId={activeCallId} />
      </div>
    );
  }

  // Frontend-side rows for the live console: microphone, room and websocket
  // state the backend can never see. Rebuilt on every render from live state.
  function micConsoleRows() {
    const now = new Date().toTimeString().slice(0, 8);
    if (!roomRef.current) {
      return [{ at_iso: now, tag: 'UI', level: 'info', message: 'room: not connected' }];
    }
    const state = roomRef.current.state || roomRef.current.connectionState || '?';
    const rows = [{ at_iso: now, tag: 'UI', level: 'info', message: `room: ${state}` }];
    if (!micDiag) {
      rows.push({ at_iso: now, tag: 'MIC', level: 'warn', message: 'microphone: no track info yet' });
    } else if (micDiag.error) {
      rows.push({ at_iso: now, tag: 'MIC', level: 'error', message: `microphone: ${micDiag.error}` });
    } else {
      rows.push({
        at_iso: now,
        tag: 'MIC',
        level: micDiag.muted ? 'warn' : 'info',
        message: `microphone: ${micDiag.muted ? 'MUTED' : 'publishing'} ${micDiag.sampleRate ?? '?'}Hz level=${Math.round(micLevel * 100)}${
          micMuted ? ' (self-muted)' : ''
        }`,
      });
    }
    return rows;
  }

  function renderLiveConsole() {
    return (
      <div style={{ marginTop: 18 }}>
        <LiveConsole active={phase !== PHASES.IDLE} localRows={micConsoleRows()} />
      </div>
    );
  }

  function renderLatencySidebar(turns) {
    return (
      <div style={{ marginTop: 18 }}>
        <b style={{ fontSize: 13 }}>Latency</b>
        <div style={{ marginTop: 8 }}>
          <LatencyPanel turns={turns} />
        </div>
        {renderDiagnosticsSidebar()}
      </div>
    );
  }

  function renderLiveLatencySidebar(turns) {
    return (
      <div style={{ marginTop: 18 }}>
        <b style={{ fontSize: 13 }}>
          Latency <span style={{ color: 'var(--dim)', fontWeight: 400 }}>· live</span>
        </b>
        <div style={{ marginTop: 8 }}>
          <LatencyPanel turns={turns} />
        </div>
        {renderDiagnosticsSidebar()}
      </div>
    );
  }

  if (phase === PHASES.TEXT) {
    return (
      <div className="pg">
        <div className="card" style={{ padding: '20px 24px' }}>
          <div className="card-h" style={{ marginBottom: 0 }}>
            <h3>Text mode · same extraction pipeline</h3>
            <span className="chip queued"><i></i>sandbox</span>
          </div>
          <TextPlayground
            key={selectedVersionId}
            versionId={selectedVersionId}
            contact={contactCard}
            onFinishReport={(res) => {
              setResult(res || {});
              setPhase(PHASES.ENDED);
            }}
          />
          <div className="form-actions space-between" style={{ marginTop: 12 }}>
            <span className="meta-line">
              {versionInfo && (
                <>
                  <span>
                    <strong>Agent:</strong> {versionInfo.agentName || '(unknown)'}
                  </span>
                  <span>
                    <strong>Version:</strong> v{versionInfo.version}
                  </span>
                </>
              )}
            </span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={backToSetup}>
              Back to setup
            </button>
          </div>
        </div>
        <aside className="card pad">
          <b style={{ fontSize: 13 }}>
            Extracted fields <span style={{ color: 'var(--dim)', fontWeight: 400 }}>· live</span>
          </b>
          <div style={{ marginTop: 8 }}>
            <p className="hint">Start a session to watch fields fill in real time.</p>
          </div>
        </aside>
      </div>
    );
  }

  if (phase === PHASES.IN_CALL || phase === PHASES.CONNECTING) {
    const connecting = phase === PHASES.CONNECTING;
    const speaking = micLevel > MIC_SPEAK_THRESHOLD;
    const orbState = connecting ? 'listening' : speaking ? 'speaking' : bargeIn ? 'interrupted' : 'listening';
    const isLive = !connecting;
    const agentFields = (result && result.extracted_fields) || [];
    const agentTurns = (result && result.transcript) || [];
    return (
      <div className="pg">
        <div className="card" style={{ padding: '10px 26px 26px' }}>
          <div className="card-h">
            <h3>{versionInfo ? `${versionInfo.agentName || 'Unknown'} · live session` : 'Live session'}</h3>
            <span className={`chip in-progress`} id="stateChip">
              <i></i>{connecting ? 'Connecting…' : speaking ? 'Listening' : bargeIn ? 'Interrupted' : 'Agent on the line'}
            </span>
          </div>
          <div className="orb-wrap">
            <button className={`big-orb${isLive ? ' live' : ''}`} data-m={orbState} aria-label="Session orb">
              <svg width="44" height="44" viewBox="0 0 24 24" fill="none">
                <rect x="9" y="3" width="6" height="11" rx="3" fill="#e9e4da" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="#e9e4da" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
            <span className="mono" style={{ fontSize: 12, color: 'var(--dim)' }}>
              {fmtClock(elapsedMs)}
            </span>
          </div>
          <div className="caps">
            {captions.length === 0 ? (
              <p className="hint" style={{ alignSelf: 'center' }}>
                {connecting ? 'Connecting…' : 'Waiting for captions…'}
              </p>
            ) : (
              captions.slice(-8).map((cap, i) => {
                const isAgent = ['agent', 'ai', 'bot', 'assistant', 'system', 'voice_agent'].includes(
                  String(cap.speaker || '').toLowerCase()
                );
                return (
                  <div key={`${cap.ts}-${i}`} className={`cap-bub ${isAgent ? 'agent' : 'caller'}`}>
                    <span className="cap-who">{isAgent ? 'Agent' : 'Caller'}</span>
                    {cap.text}
                  </div>
                );
              })
            )}
          </div>
          <div className="form-actions" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
            <button
              type="button"
              className={`btn btn-sm ${micMuted ? 'btn-danger' : ''}`}
              onClick={toggleMute}
              disabled={connecting}
              title="Mute or unmute your microphone. While muted the agent cannot hear you."
              style={{ marginRight: 8 }}
            >
              {micMuted ? 'Unmute mic' : 'Mute mic'}
            </button>
            <button type="button" className="btn btn-danger btn-sm" onClick={endCall} disabled={connecting}>
              End call
            </button>
          </div>
          {/* Why "the agent cannot hear me" is not guessable from the agent side:
              a silent published track (permission/device/processing) and a
              working track with a failing STT look identical from here. */}
          {micDiag && (
            <div className="dp-wrap" style={{ marginTop: 10 }}>
              <div className="dp-body">
                <div className="dp-section-title" style={{ marginTop: 4 }}>Your microphone</div>
                {micDiag.error ? (
                  <div className="dp-error">{micDiag.error}</div>
                ) : (
                  <div className="dp-member">
                    <span className="dp-name">track</span>
                    <span className="dp-model">{micDiag.readyState || 'unknown'}</span>
                    <span className={micDiag.muted ? 'dp-missing' : 'dp-ok'}>
                      {micDiag.muted ? 'MUTED' : 'publishing'}
                    </span>
                    <span className="dp-cap">{micDiag.sampleRate ?? '?'} Hz</span>
                    <span className="dp-cap">{micDiag.channelCount ?? '?'} ch</span>
                    <span className="dp-cap">AEC {String(micDiag.echoCancellation)}</span>
                    <span className="dp-cap">NS {String(micDiag.noiseSuppression)}</span>
                    <span className="dp-cap">level {Math.round(micLevel * 100)}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {statusNote && <div className="banner banner-info">{statusNote}</div>}

        <aside className="card pad">
          <b style={{ fontSize: 13 }}>
            Extracted fields <span style={{ color: 'var(--dim)', fontWeight: 400 }}>· live</span>
          </b>
          <div style={{ marginTop: 8 }}>
            {agentFields.map((f, i) => (
              <div key={`${f.field_name}-${i}`} className="frow2">
                <span className="k">{f.field_name}</span>
                <span>
                  {f.field_value != null ? String(f.field_value) : '— not captured yet'}{' '}
                  <span className={`confchip ${confidenceClass(f.confidence)}`}>
                    {f.confidence != null && !Number.isNaN(Number(f.confidence))
                      ? `${Math.round(
                          Number(f.confidence) <= 1 ? Number(f.confidence) * 100 : Number(f.confidence)
                        )}%`
                      : ''}
                  </span>
                </span>
              </div>
            ))}
          </div>
          {renderLiveLatencySidebar(agentTurns)}
          {renderLiveConsole()}
        </aside>
      </div>
    );
  }

  if (phase === PHASES.ENDED) {
    const turns = (result && result.transcript) || [];
    const fields = (result && result.extracted_fields) || [];
    const resolvedCallId = result && (result.call_id || (sessionRef.current && sessionRef.current.call_id));
    return (
      <div className="pg">
        <div className="card" style={{ padding: '24px' }}>
          <button type="button" className="btn btn-ghost self-start" onClick={backToSetup}>
            ← Run another test
          </button>

          <div className="banner banner-success" style={{ marginTop: 12 }}>
            <strong>Call finished.</strong>{' '}
            {result && result.duration_seconds != null && <>Duration: {fmtClock(result.duration_seconds * 1000)}. </>}
            {result && result.flagged_for_human ? 'This session was flagged for human review.' : null}
          </div>

          {completeError && (
            <div className="banner banner-error" style={{ marginTop: 12 }}>
              {completeError}{' '}
              <button type="button" className="btn btn-secondary btn-sm" onClick={completeSession} disabled={completing}>
                {completing ? 'Retrying…' : 'Retry'}
              </button>
            </div>
          )}

          {!result && !completeError && (
            <div className="loading-page" style={{ marginTop: 20 }}>
              <span className="spinner" /> Collecting transcript and results…
            </div>
          )}

          {result && (
            <>
              <div style={{ marginTop: 20 }}>
                <h3 className="card-title">Transcript</h3>
                {turns.length === 0 ? (
                  <p className="hint">No transcript was recorded for this session.</p>
                ) : (
                  <div className="transcript" aria-live="polite">
                    {turns.map((t, i) => {
                      const isAgent = ['agent', 'ai', 'bot', 'assistant', 'system', 'voice_agent'].includes(
                        String(t.speaker || '').toLowerCase()
                      );
                      const displayName = isAgent
                        ? 'Agent'
                        : t.speaker
                          ? String(t.speaker)
                            .replace(/[_-]+/g, ' ')
                            .replace(/\b\w/g, (ch) => ch.toUpperCase())
                          : 'Caller';
                      return (
                        <div key={t.turn_index != null ? `turn-${t.turn_index}` : `i-${i}`} className={`cap-bub ${isAgent ? 'agent' : 'caller'}`}>
                          <span className="cap-who">{displayName}</span>
                          {cleanTranscriptText(t.text)}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {result.outcome && (
                <p className="hint" style={{ marginTop: 12 }}>
                  Outcome: <span className="chip">{String(result.outcome)}</span>
                </p>
              )}

              {versionInfo && versionInfo.agentName && (
                <p className="hint" style={{ marginTop: 12 }}>
                  Tested <strong>{versionInfo.agentName}</strong> v{versionInfo.version}.{' '}
                  <Link to="/agents">Back to agents</Link> · <Link to="/campaigns">Launch this agent as a campaign</Link>
                </p>
              )}
            </>
          )}
        </div>

        <aside className="card pad">
          <b style={{ fontSize: 13 }}>Extracted fields</b>
          <div style={{ marginTop: 8 }}>
            {fields.length === 0 ? (
              <p className="hint">
                No structured fields were extracted during this call. The agent collects fields during calls; check the
                transcript for what it asked.
              </p>
            ) : (
              fields.map((f, i) => (
                <div key={`${f.field_name}-${i}`} className="frow2">
                  <span className="k">{f.field_name}</span>
                  <span>
                    {f.field_value != null ? String(f.field_value) : '—'}{' '}
                    <span className={`confchip ${confidenceClass(f.confidence)}`}>
                      {f.confidence != null && !Number.isNaN(Number(f.confidence))
                        ? `${Math.round(
                            Number(f.confidence) <= 1 ? Number(f.confidence) * 100 : Number(f.confidence)
                          )}%`
                        : ''}
                    </span>
                  </span>
                </div>
              ))
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
            {resolvedCallId && (
              <>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => window.open(callExportUrl(resolvedCallId, 'csv'), '_blank')}
                >
                  Export CSV
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => window.open(callExportUrl(resolvedCallId, 'xlsx'), '_blank')}
                >
                  Export XLSX
                </button>
              </>
            )}
          </div>
          {renderLatencySidebar(turns)}
        </aside>
      </div>
    );
  }

  // ------------------------------------------------------------------ setup

  return (
    <div className="pg">
      <div className="card" style={{ padding: '24px' }}>
        <div className="card-h">
          <h3>Set up a test session</h3>
          <span style={{ fontSize: 12, color: 'var(--dim)' }}>sandbox</span>
        </div>

        {fatalError && (
          <div style={{ marginTop: 20 }}>
            <div className="banner banner-error">{fatalError}</div>
            <div className="form-actions" style={{ marginTop: 12 }}>
              <button type="button" className="btn btn-primary" onClick={backToSetup}>
                Back to setup
              </button>
            </div>
          </div>
        )}

        {!fatalError && (
          <div style={{ marginTop: 20 }}>
            <div className="mode-toggle">
              <button
                type="button"
                className={mode === MODES.VOICE ? 'on' : ''}
                onClick={() => {
                  setMode(MODES.VOICE);
                  setConnectError(null);
                }}
              >
                Voice session
              </button>
              <button
                type="button"
                className={mode === MODES.TEXT ? 'on' : ''}
                onClick={() => {
                  setMode(MODES.TEXT);
                  setConnectError(null);
                }}
              >
                Text mode
              </button>
            </div>

            {!routeVersionId && (
              <div style={{ marginTop: 20 }}>
                {agentsError && (
                  <div className="banner banner-error">
                    {agentsError}{' '}
                    <Link to="/agents/new" className="btn btn-secondary btn-sm">
                      Create an agent
                    </Link>
                  </div>
                )}
                {!agentsError && agents && agents.length === 0 && (
                  <div className="empty-state">
                    No agents yet — build one first.
                    <div className="form-actions">
                      <Link to="/agents/new" className="btn btn-primary">
                        + New Agent
                      </Link>
                    </div>
                  </div>
                )}
                {!agentsError && agents && agents.length > 0 && (
                  <>
                    <div className="fieldrow" style={{ marginTop: 12 }}>
                      <label>Agent</label>
                      <select
                        value={selectedAgentId}
                        onChange={(e) => setSelectedAgentId(e.target.value)}
                      >
                        {agents.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="fieldrow" style={{ marginTop: 8 }}>
                      <label>Version</label>
                      <select
                        value={selectedVersionId}
                        onChange={(e) => setSelectedVersionId(e.target.value)}
                        disabled={versionsLoading}
                      >
                        {versionsLoading && <option>Loading…</option>}
                        {!versionsLoading &&
                          versions.map((v) => (
                            <option key={v.id} value={v.id}>
                              v{v.version} — saved {new Date(v.created_at).toLocaleString()}
                            </option>
                          ))}
                        {!versionsLoading && versions.length === 0 && <option value="">No saved versions yet</option>}
                      </select>
                    </div>
                  </>
                )}
                {infoError && <p className="hint hint-error" style={{ marginTop: 8 }}>{infoError}</p>}
              </div>
            )}
            <details className="card" open style={{ marginTop: 12 }}>
              <summary>Who are we calling? (optional lead card)</summary>
              <LeadCardForm value={contactCard} onChange={setContactCard} defaults={ABSENT_STUDENT_DEFAULTS} />
            </details>

            {selectedVersionId && (
              <div style={{ marginTop: 12 }}>
                <TestCallPanel versionId={selectedVersionId} contactCard={contactCard} />
              </div>
            )}

            {selectedVersionId && mode === MODES.VOICE && (
              <div style={{ marginTop: 20 }}>
                <p style={{ fontSize: 13.5, lineHeight: 1.6 }}>
                  Your browser will ask for microphone permission — this is required so the agent can hear you. Audio
                  plays through your speakers or headset, exactly like a phone call. The whole conversation is recorded
                  as a test session you can review afterwards.
                </p>
                <p className="hint">
                  Tip: use headphones to avoid echo. If nothing seems to happen, check that the correct microphone is
                  selected in your browser's site settings.
                </p>
              </div>
            )}

            {selectedVersionId && mode === MODES.TEXT && (
              <div style={{ marginTop: 20 }}>
                <p className="hint">
                  No microphone or voice room needed. The agent opens with its disclosure and first question; reply by
                  typing. Extraction and the final report work exactly like a voice test.
                </p>
              </div>
            )}

            {selectedVersionId && (
              <div style={{ display: 'flex', gap: 12, marginTop: 26 }}>
                {mode === MODES.VOICE && (
                  <>
                    {versionInfo && (
                      <span className="meta-line" style={{ alignSelf: 'center', fontSize: 13 }}>
                        <strong>Agent:</strong> {versionInfo.agentName || '(unknown)'} · v{versionInfo.version}
                      </span>
                    )}
                    {connectError && <div className="banner banner-error" style={{ width: '100%' }}>{connectError}</div>}
                    <button
                      type="button"
                      className="btn btn-primary"
                      style={{ padding: '13px 26px' }}
                      onClick={startCall}
                      disabled={phase === PHASES.CONNECTING || !selectedVersionId}
                    >
                      {phase === PHASES.CONNECTING ? 'Connecting…' : 'Start Voice Session'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => {
                        setResult(null);
                        setFatalError(null);
                        setConnectError(null);
                        setPhase(PHASES.TEXT);
                      }}
                    >
                      Start in Text Mode
                    </button>
                  </>
                )}
                {mode === MODES.TEXT && (
                  <>
                    {versionInfo && (
                      <span className="meta-line" style={{ alignSelf: 'center', fontSize: 13 }}>
                        <strong>Agent:</strong> {versionInfo.agentName || '(unknown)'} · v{versionInfo.version}
                      </span>
                    )}
                    {connectError && <div className="banner banner-error" style={{ width: '100%' }}>{connectError}</div>}
                    <button
                      type="button"
                      className="btn btn-primary"
                      style={{ padding: '13px 26px' }}
                      onClick={() => {
                        setResult(null);
                        setFatalError(null);
                        setConnectError(null);
                        setPhase(PHASES.TEXT);
                      }}
                    >
                      Start in Text Mode
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => {
                        setMode(MODES.VOICE);
                        setConnectError(null);
                      }}
                    >
                      Voice Session
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <aside className="card pad">
        <b style={{ fontSize: 13 }}>
          Extracted fields <span style={{ color: 'var(--dim)', fontWeight: 400 }}>· live</span>
        </b>
        <div style={{ marginTop: 8 }}>
          <p className="hint">Start a session to watch fields fill in real time.</p>
        </div>
        <div style={{ marginTop: 18 }} />
      </aside>
    </div>
  );
}
