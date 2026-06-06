import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRM, VRMSchema } from "@pixiv/three-vrm";

let renderer, scene, camera, currentVRM, lookAtTarget;
let controls;
let containerEl;
let running = false;
let animationId;

const EMOTION_MAP = {
  neutral: "neutral",
  happy: "happy",
  sad: "sad",
  angry: "angry",
  surprised: "surprised",
  blush: "relaxed",
  thinking: "neutral",
};

export async function startVRM(container, modelPath) {
  if (running) return;
  containerEl = container;
  containerEl.innerHTML = "";

  var w = containerEl.clientWidth || 500;
  var h = containerEl.clientHeight || 700;

  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(w, h);
  renderer.shadowMap.enabled = true;
  containerEl.appendChild(renderer.domElement);

  scene = new THREE.Scene();

  camera = new THREE.PerspectiveCamera(30, w / h, 0.1, 20);
  camera.position.set(0, 1.35, 2.4);
  camera.lookAt(0, 1.25, 0);

  var dirLight = new THREE.DirectionalLight(0xffffff, 1.6);
  dirLight.position.set(0.5, 2, 1.5);
  dirLight.castShadow = true;
  scene.add(dirLight);
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));

  lookAtTarget = new THREE.Object3D();
  lookAtTarget.position.set(0, 1.4, 0.5);
  scene.add(lookAtTarget);

  if (modelPath) {
    try {
      await loadVRM(modelPath);
    } catch (e) {
      console.warn("VRM load failed:", e);
    }
  }

  running = true;
  animate();
}

function setupVRM(vrm) {
  currentVRM = vrm;
  scene.add(vrm.scene);

  var head = vrm.humanoid.getNormalizedBoneNode("head");
  if (head) {
    vrm.lookAt.target = lookAtTarget;
    vrm.lookAt.autoBlink = true;
    head.add(lookAtTarget);
  }

  vrm.expressionManager.setValue("neutral", 1.0);
}

function loadVRM(path) {
  return new Promise(function (resolve, reject) {
    var loader = new GLTFLoader();
    loader.load(
      path,
      function (gltf) {
        VRM.from(gltf).then(function (vrm) {
          setupVRM(vrm);
          resolve();
        }).catch(reject);
      },
      undefined,
      reject
    );
  });
}

export function setVRMExpression(emotion) {
  if (!currentVRM) return;
  var expr = EMOTION_MAP[emotion] || "neutral";
  if (currentVRM.expressionManager) {
    currentVRM.expressionManager.setValue(expr, 1.0);
  }
}

export function stopVRM() {
  running = false;
  if (animationId) cancelAnimationFrame(animationId);
  if (currentVRM) { currentVRM.dispose(); currentVRM = null; }
  if (renderer) { renderer.dispose(); renderer = null; }
  scene = null; camera = null; lookAtTarget = null;
  if (containerEl) containerEl.innerHTML = "";
}

function animate() {
  if (!running) return;
  animationId = requestAnimationFrame(animate);
  if (currentVRM) currentVRM.update(0.016);
  if (renderer && scene && camera) {
    renderer.render(scene, camera);
  }
}
