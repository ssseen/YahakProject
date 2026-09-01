import { renderHome } from './pages/home.js';
import { renderMenu } from './pages/menu.js';
import { renderPhotoProcessing } from './pages/photo-processing.js';
import { renderVoiceProcessing } from './pages/voice-processing.js';
import { renderSolve } from './pages/solve.js';
import { renderHeader } from './components/header.js';

// 경로별 렌더 함수 + 헤더 표시 여부 + css 파일명
const routes = {
  '/': { render: renderHome, css: 'home', showHeader: false },
  '/menu': { render: renderMenu, css: 'menu', showHeader: true },
  '/camera': { render: renderPhotoProcessing, css: 'camera', showHeader: false },
  '/voice': { render: renderVoiceProcessing, css: 'voice', showHeader: true },
  '/solve': { render: renderSolve, css: 'solve', showHeader: true },
};

// 뒤로가기 판단을 위한 경로 순서 (숫자가 클수록 "더 깊은" 화면)
const routeOrder = ['/', '/menu', '/camera', '/voice', '/solve'];

let currentPath = '/';
let currentCssLink = null;

function loadPageCSS(name) {
  if (currentCssLink) currentCssLink.remove();
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = `css/pages/${name}.css`;
  link.dataset.pageCss = 'true';
  document.head.appendChild(link);
  currentCssLink = link;
}

export function navigate(path) {
  window.location.hash = `#${path}`;
}

function router() {
  const app = document.getElementById('app');
  const headerRoot = document.getElementById('header-root');
  const rawHash = window.location.hash.slice(1) || '/';
  const [nextPath] = rawHash.split('?'); // ?step=... 같은 디버그용 쿼리는 라우팅 매칭에서 제외
  const route = routes[nextPath] || routes['/'];

  // 방향 판단: 더 깊은 화면으로 가면 오른쪽에서, 얕은 화면으로 돌아가면 왼쪽에서 슬라이드
  const goingForward = routeOrder.indexOf(nextPath) >= routeOrder.indexOf(currentPath);
  currentPath = nextPath;

  loadPageCSS(route.css);

  headerRoot.innerHTML = '';
  if (route.showHeader) {
    headerRoot.appendChild(renderHeader({ onBack: () => window.history.back() }));
  }

  app.classList.remove('page-enter-right', 'page-enter-left');
  // 리플로우 강제 후 클래스 재적용 (연속 네비게이션 시 애니메이션 재생 보장)
  void app.offsetWidth;
  app.innerHTML = '';
  route.render(app, { navigate });
  const enterClass = goingForward ? 'page-enter-right' : 'page-enter-left';
  app.classList.add(enterClass);
  // 애니메이션이 끝나면 클래스를 지워서 transform 잔여값을 없앤다.
  // (transform이 0이라도 남아있으면, #app 자손의 position:fixed가 화면이 아니라
  //  #app 기준으로 동작하게 돼서, 하단 고정 네비 같은 요소가 콘텐츠 길이에 따라
  //  같이 움직이는 버그가 생김)
  app.addEventListener(
    'animationend',
    () => app.classList.remove(enterClass),
    { once: true }
  );
}

export function initRouter() {
  window.addEventListener('hashchange', router);
  window.addEventListener('DOMContentLoaded', router);
  // 스크립트가 DOMContentLoaded 이후 로드되는 경우 대비
  if (document.readyState !== 'loading') router();
}