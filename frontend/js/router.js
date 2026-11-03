import { renderHome } from './pages/home.js';
import { renderMenu } from './pages/menu.js';
import { renderPhotoProcessing } from './pages/photo-processing.js';
import { renderVoiceProcessing } from './pages/voice-processing.js';
import { renderSolve } from './pages/solve.js';
import { renderHeader } from './components/header.js';
import { renderPractice } from './pages/practice.js';
import { renderHowto } from './pages/howto.js';
import { resetQuestionFlow } from './state.js';

// 경로별 렌더 함수 + 헤더 표시 여부 + css 파일명
const routes = {
  '/': { render: renderHome, css: 'home', showHeader: false },
  '/menu': { render: renderMenu, css: 'menu', showHeader: true },
  '/camera': { render: renderPhotoProcessing, css: 'camera', showHeader: false },
  '/voice': { render: renderVoiceProcessing, css: 'voice', showHeader: true },
  '/solve': { render: renderSolve, css: 'solve', showHeader: true },
  '/practice': { render: renderPractice, css: 'solve', showHeader: true },
  '/howto': { render: renderHowto, css: 'howto', showHeader: true },
};

// '뒤로 가기' 버튼이 갈 화면 (브라우저 기록 대신 고정된 이전 화면으로 이동)
// 예전엔 history.back()이라 해설 화면 -> 음성 화면 -> 카메라 화면(이미 찍은 사진을 또 보내고
// 다시 음성 화면으로 넘어감)처럼 끝난 단계를 다시 실행해서 에러가 났음
const BACK_TARGET = {
  '/menu': '/',
  '/camera': '/menu',
  '/voice': '/menu',
  '/solve': '/menu',
  '/practice': '/solve',
};
let howtoReturnPath = '/'; // 사용방법은 열었던 화면(첫 화면/메뉴)으로 돌아감

// 뒤로가기 판단을 위한 경로 순서 (숫자가 클수록 "더 깊은" 화면)
const routeOrder = ['/', '/howto', '/menu', '/camera', '/voice', '/solve', '/practice'];

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

// 고정된 이전 화면으로 이동. 기록을 쌓지 않도록 replace 사용
export function goBack() {
  const target = currentPath === '/howto' ? howtoReturnPath : (BACK_TARGET[currentPath] || '/');
  if (target === '/' || target === '/menu') resetQuestionFlow(); // 문제 흐름을 벗어나면 사진/해설 비우기
  window.location.replace(`#${target}`);
}

function router() {
  const app = document.getElementById('app');
  const headerRoot = document.getElementById('header-root');
  const rawHash = window.location.hash.slice(1) || '/';
  const [nextPath] = rawHash.split('?'); // ?step=... 같은 디버그용 쿼리는 라우팅 매칭에서 제외
  const route = routes[nextPath] || routes['/'];

  // 방향 판단: 더 깊은 화면으로 가면 오른쪽에서, 얕은 화면으로 돌아가면 왼쪽에서 슬라이드
  const goingForward = routeOrder.indexOf(nextPath) >= routeOrder.indexOf(currentPath);
  if (nextPath === '/howto' && currentPath !== '/howto') {
    howtoReturnPath = currentPath === '/menu' ? '/menu' : '/';
  }
  currentPath = nextPath;

  loadPageCSS(route.css);

  headerRoot.innerHTML = '';
  if (route.showHeader) {
    headerRoot.appendChild(renderHeader({ onBack: goBack }));
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
  // 첫 화면은 한 번만 그린다 (예전엔 둘 다 실행돼서 첫 화면이 두 번 그려졌고,
  // 카메라 화면이면 카메라를 두 번 켜서 하나가 안 꺼진 채 남았음)
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', router, { once: true });
  } else {
    router();
  }
}