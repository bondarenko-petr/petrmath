import React, {useEffect, useRef, useState} from 'react';
import {Room, RoomEvent, Track} from 'livekit-client';

const icons = {
 microphone: <><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3"/></>,
 camera: <><rect x="3" y="6" width="12" height="12" rx="2"/><path d="m15 10 6-4v12l-6-4"/></>,
 expand: <path d="M14 4h6v6m0-6-6 6M4 14v6h6m-6 0 6-6"/>,
 minimize: <path d="M5 12h14"/>,
 leave: <path d="M3 13c0-3 4-5 9-5s9 2 9 5v3h-5l-1-3a11 11 0 0 0-6 0l-1 3H3z"/>,
};

function CallButton({icon, label, off, pressed, disabled, onClick}) {
 return <button type="button" className={'lesson-call-icon' + (icon === 'leave' ? ' lesson-call-leave' : '')}
  title={label} aria-label={label} aria-pressed={pressed} disabled={disabled} onClick={onClick}>
  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"
   strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
   {icons[icon]}
   {off && <><path d="M3 3l18 18" stroke="white" strokeWidth="4"/><path d="M3 3l18 18"/></>}
  </svg>
 </button>;
}

export default function LessonCall({lessonId, onClose}) {
 const local = useRef(null);
 const remote = useRef(null);
 const audio = useRef(null);
 const [layout, setLayout] = useState('compact');
 const [peer, setPeer] = useState(null);
 const [peerVideo, setPeerVideo] = useState(false);
 const session = useRef(null);
 const [room, setRoom] = useState(null);
 const [status, setStatus] = useState('Подключаемся…');
 const [microphone, setMicrophone] = useState(false);
 const [camera, setCamera] = useState(false);
 const [busy, setBusy] = useState(false);
 const [audioBlocked, setAudioBlocked] = useState(false);

 useEffect(() => {
  let closed = false;
  const request = new AbortController();
  const connection = new Room();
  session.current = connection;
  const attach = track => {
   if (closed) return;
   if (track.kind === Track.Kind.Video) {
    remote.current?.append(track.attach());
    setPeerVideo(true);
   } else audio.current?.append(track.attach());
  };
  const detach = track => track.detach().forEach(element => element.remove());
  const updatePeer = () => {
   if (!closed) {
    const participant = connection.remoteParticipants.values().next().value;
    setPeer(participant ? participant.name || 'Собеседник' : null);
   }
  };
  connection.on(RoomEvent.TrackSubscribed, attach)
   .on(RoomEvent.TrackUnsubscribed, track => {
    detach(track);
    if (!closed && track.kind === Track.Kind.Video) setPeerVideo(false);
   })
   .on(RoomEvent.ParticipantConnected, updatePeer)
   .on(RoomEvent.ParticipantDisconnected, updatePeer)
   .on(RoomEvent.TrackMuted, (publication, participant) => {
    if (!closed && !participant.isLocal && publication.source === Track.Source.Camera) setPeerVideo(false);
   })
   .on(RoomEvent.TrackUnmuted, (publication, participant) => {
    if (!closed && !participant.isLocal && publication.source === Track.Source.Camera) setPeerVideo(Boolean(publication.track));
   })
   .on(RoomEvent.LocalTrackPublished, publication => {
    if (!closed && local.current && publication.source === Track.Source.Camera && publication.track) {
     const preview = publication.track.attach();
     preview.muted = true;
     preview.dataset.localCamera = 'true';
     local.current.append(preview);
    }
   })
   .on(RoomEvent.LocalTrackUnpublished, publication => {
    if (publication.track) detach(publication.track);
    local.current?.querySelectorAll('video').forEach(element => {
     if (element.dataset.localCamera) element.remove();
    });
   })
   .on(RoomEvent.AudioPlaybackStatusChanged, () => {
    if (!closed) setAudioBlocked(!connection.canPlaybackAudio);
   })
   .on(RoomEvent.Reconnecting, () => { if (!closed) setStatus('Восстанавливаем связь…'); })
   .on(RoomEvent.Reconnected, () => { if (!closed) setStatus('Подключено'); })
   .on(RoomEvent.Disconnected, () => {
    if (!closed) {
     setRoom(null);
     setStatus('Звонок завершён. Закройте панель, чтобы подключиться снова.');
    }
   });

  async function connect() {
   try {
    const response = await fetch('/api/lessons/' + lessonId + '/call/token', {
     method: 'POST', headers: {'X-Requested-With': 'KrugPi'}, signal: request.signal,
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || 'Не удалось подключиться');
    if (closed) return;
    await connection.connect(data.url, data.token);
    if (closed) {
     await connection.disconnect();
     return;
    }
    updatePeer();
    setRoom(connection);
    setStatus('Подключено');
    try {
     await connection.localParticipant.setMicrophoneEnabled(true);
     if (closed) { await connection.disconnect(); return; }
     setMicrophone(true);
    } catch {
     if (!closed) setStatus('Микрофон не включён. Разрешите доступ в браузере и нажмите значок микрофона.');
    }
   } catch (error) {
    if (!closed) setStatus(error.message || 'Видеосвязь недоступна');
   }
  }
  const disconnect = event => {
   closed = true;
   session.current = null;
   for (const publication of connection.localParticipant.trackPublications.values()) publication.track?.stop();
   const pending = connection.disconnect();
   if (event?.detail && Array.isArray(event.detail)) event.detail.push(pending);
  };
  window.addEventListener('board-exit', disconnect);
  window.addEventListener('pagehide', disconnect);
  void connect();
  return () => {
   window.removeEventListener('board-exit', disconnect);
   window.removeEventListener('pagehide', disconnect);
   closed = true;
   request.abort();
   session.current = null;
   void connection.disconnect();
  };
 }, [lessonId]);

 async function toggle(kind) {
  setBusy(true);
  try {
   if (kind === 'microphone') {
    await room.localParticipant.setMicrophoneEnabled(!microphone);
    if (session.current === room) setMicrophone(!microphone);
   } else {
    await room.localParticipant.setCameraEnabled(!camera);
    if (session.current === room) setCamera(!camera);
   }
   if (session.current === room) setStatus('Подключено');
  } catch {
   if (session.current === room) setStatus('Проверьте разрешения браузера на камеру и микрофон.');
  } finally {
   if (session.current === room) setBusy(false);
  }
 }
 const expanded = layout === 'expanded';
 const hidden = layout === 'hidden';
 return <section className={'lesson-call lesson-call-' + layout} aria-label="Видеосвязь">
  <p className={room && status.startsWith('Подключено') && !expanded ? 'lesson-call-status-quiet' : undefined}
   role="status">{status}</p>
  <div className="lesson-call-media" hidden={hidden}>
   <div className="lesson-call-tile lesson-call-peer">
    <div ref={remote} hidden={!peerVideo} className="lesson-call-stream"/>
    <span>{peer || 'Ожидаем собеседника'}</span>
   </div>
   <div className="lesson-call-tile lesson-call-self" hidden={!expanded}>
    <div ref={local} hidden={!camera} className="lesson-call-stream"/>
    <span>Вы</span>
   </div>
  </div>
  <div ref={audio}/>
  {audioBlocked && room && <button className="lesson-call-audio" onClick={() => void room.startAudio().catch(() => setStatus('Браузер заблокировал воспроизведение звука.'))}>Воспроизвести звук</button>}
  <div className="lesson-call-actions">
   <CallButton icon="microphone" off={!microphone} pressed={microphone} disabled={!room || busy}
    label={microphone ? 'Выключить микрофон' : 'Включить микрофон'} onClick={() => void toggle('microphone')}/>
   <CallButton icon="camera" off={!camera} pressed={camera} disabled={!room || busy}
    label={camera ? 'Выключить камеру' : 'Включить камеру'} onClick={() => void toggle('camera')}/>
   <CallButton icon="expand" label={hidden ? 'Показать миниатюру' : 'Развернуть звонок'}
    disabled={expanded} onClick={() => setLayout(hidden ? 'compact' : 'expanded')}/>
   <CallButton icon="minimize" label={expanded ? 'Уменьшить до миниатюры' : 'Скрыть видео'}
    disabled={hidden} onClick={() => setLayout(expanded ? 'compact' : 'hidden')}/>
   <CallButton icon="leave" label="Выйти из звонка" onClick={onClose}/>
  </div>
 </section>;
}
