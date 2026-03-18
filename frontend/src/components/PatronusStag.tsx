import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Canvas, useFrame, useGraph } from '@react-three/fiber';
import { useGLTF, OrbitControls, Points, PointMaterial } from '@react-three/drei';
import * as THREE from 'three';
import './PatronusStag.css';

interface PatronusStagProps {
  onComplete: () => void;
}

// Ensure the GLB file is available in public/models/stag.glb
const MODEL_PATH = '/models/stag.glb';

function Model({ isDissolving }: { isDissolving: boolean }) {
  const group = useRef<THREE.Group>(null);
  const { scene } = useGLTF(MODEL_PATH);
  
  // Extract geometry from the first mesh found in the GLTF
  // Extract geometry from the GLTF
  const { nodes } = useGraph(scene);
  const geometry = useMemo(() => {
    let foundGeometry = new THREE.BufferGeometry();
    console.log("GLTF Nodes found:", Object.keys(nodes));
    
    // Attempt to specifically target the stag geometry and ignore the base
    for (const key in nodes) {
      const node = nodes[key] as THREE.Mesh;
      if (node.isMesh && node.geometry) {
        // If we know the likely name of the base, we can skip it. 
        // For now, since we don't know the exact names, we log them and filter generally.
        // We'll exclude common base names.
        const name = key.toLowerCase();
        if (name.includes('base') || name.includes('pedestal') || name.includes('plane') || name.includes('cylinder')) {
             console.log("Skipping likely base mesh:", key);
             continue;
        }
        
        console.log("Using mesh for Stag:", key);
        foundGeometry = node.geometry;
        break; // take the first mesh that isn't a base
      }
    }
    // Calculate bounding box to center the model easily
    foundGeometry.computeBoundingBox();
    const box = foundGeometry.boundingBox;
    if (box) {
        const center = new THREE.Vector3();
        box.getCenter(center);
        foundGeometry.translate(-center.x, -center.y, -center.z); // Center it at origin
    }
    return foundGeometry;
  }, [nodes]);

  // Extract vertices to place glowing "neurons"
  const vertices = useMemo(() => {
    if (!geometry.attributes.position) return new Float32Array(0);
    return geometry.attributes.position.array as Float32Array;
  }, [geometry]);

  useFrame((state) => {
    if (!group.current) return;
    const time = state.clock.getElapsedTime();
    
    if (isDissolving) {
      // Rapidly spin and fade out
      group.current.rotation.y += 0.05;
      group.current.scale.multiplyScalar(0.95);
    } else {
      // Gentle floating animation
      group.current.position.y = Math.sin(time) * 0.1;
      group.current.rotation.y -= 0.002;
    }
  });

  return (
    <group ref={group} dispose={null} scale={[5, 5, 5]}>
      {/* 1. Wireframe Neural Web wrapping the geometry */}
      <mesh geometry={geometry}>
        <meshStandardMaterial 
          color="#bae6fd" 
          emissive="#0284c7"
          emissiveIntensity={2}
          wireframe={true} 
          transparent={true}
          opacity={isDissolving ? 0 : 0.4}
        />
      </mesh>
      
      {/* 2. Glowing Neuron Synapses sprinkled on the vertices */}
      <Points positions={vertices} stride={3}>
        <PointMaterial 
          transparent 
          color="#e0f2fe" 
          size={0.05} 
          sizeAttenuation={true} 
          depthWrite={false}
          opacity={isDissolving ? 0 : 0.8}
        />
      </Points>
    </group>
  );
}

export const PatronusStag: React.FC<PatronusStagProps> = ({ onComplete }) => {
  const [isDissolving, setIsDissolving] = useState(false);
  const [showText, setShowText] = useState(false);

  useEffect(() => {
    // Initial text sequence
    setTimeout(() => setShowText(true), 1500);
    
    // Auto transition
    const dissolveTimeout = setTimeout(() => {
        setIsDissolving(true);
        setTimeout(onComplete, 1500); 
    }, 6000);

    return () => clearTimeout(dissolveTimeout);
  }, [onComplete]);

  return (
    <div className={`patronus-container ${isDissolving ? 'dissolving' : ''}`} onClick={() => {
        if(!isDissolving) {
            setIsDissolving(true);
            setTimeout(onComplete, 1500);
        }
    }}>
      <Canvas 
        className="patronus-canvas"
        camera={{ position: [0, 0, 5], fov: 45 }}
        gl={{ alpha: true, antialias: true }}
      >
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} intensity={2} color="#bae6fd" />
        
        {/* React Suspense waits for the GLB to load */}
        <React.Suspense fallback={null}>
          <Model isDissolving={isDissolving} />
        </React.Suspense>
        
        <OrbitControls enableZoom={false} enablePan={false} autoRotate={!isDissolving} autoRotateSpeed={2} />
      </Canvas>
      
      <div className={`patronus-overlay ${showText && !isDissolving ? 'visible' : ''}`}>
        <h1 className="patronus-title">PhoneAgent</h1>
        <p className="patronus-subtitle">Neural Web Initialized. Semantic Memory Online.</p>
        <span className="patronus-prompt">Click to engage</span>
      </div>
    </div>
  );
};
