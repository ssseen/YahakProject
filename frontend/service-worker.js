// 기본 오프라인 캐싱 - 앱 껍데기(HTML/CSS/JS/이미지)만 캐싱하고,
// 실제 API 호출(/api/analyze, /transcribe)은 캐싱하지 않는다 (매번 새 데이터가 필요하니까).
const CACHE_NAME = 'geomgosim-v1';

// 앱 실행에 꼭 필요한 최소 파일들. 새 페이지/이미지를 추가하면 여기도 같이 추가해야 함.
const CORE_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './css/common.css',
  './css/pages/home.css',
  './css/pages/menu.css',
  './css/pages/camera.css',
  './css/pages/voice.css',
  './css/pages/solve.css',
  './js/app.js',
  './js/router.js',
  './js/state.js',
  './js/pages/home.js',
  './js/pages/menu.js',
  './js/pages/photo-processing.js',
  './js/pages/voice-processing.js',
  './js/pages/solve.js',
  './js/components/header.js',
  './js/components/settings-modal.js',
  './js/components/word-popup.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // 예전 버전 캐시는 정리
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 백엔드 API 요청(analyze, transcribe)은 캐싱하지 않고 그냥 네트워크로 통과시킴
  if (url.pathname.includes('/api/') || url.pathname.includes('/transcribe')) {
    return; // 이 요청은 service worker가 관여하지 않음 (기본 브라우저 동작)
  }

  // 그 외(앱 껍데기, 이미지 등)는 캐시 우선 - 있으면 캐시에서, 없으면 네트워크에서 받아오고 캐시에 저장
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        // 성공 응답만 캐시에 저장 (에러 응답을 캐싱하면 안 됨)
        if (response.ok) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
        }
        return response;
      });
    })
  );
});