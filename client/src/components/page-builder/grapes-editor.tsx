import { useEffect, useRef, useCallback } from 'react';
import grapesjs, { Editor } from 'grapesjs';
import 'grapesjs/dist/css/grapes.min.css';
import '@/styles/grapes-custom.css';

interface GrapesEditorProps {
  initialContent?: { html: string; css: string; components?: any; styles?: any };
  onSave: (data: { html: string; css: string; components: any; styles: any }) => void;
  onLoad?: () => void;
}

export function GrapesEditor({ initialContent, onSave, onLoad }: GrapesEditorProps) {
  const editorRef = useRef<Editor | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const onSaveRef = useRef(onSave);
  
  // Keep the ref updated with latest callback
  useEffect(() => {
    onSaveRef.current = onSave;
  }, [onSave]);

  const initEditor = useCallback(() => {
    if (!containerRef.current || editorRef.current) return;

    const editor = grapesjs.init({
      container: containerRef.current,
      fromElement: false,
      height: '100%',
      width: 'auto',
      storageManager: false,
      panels: { defaults: [] },
      deviceManager: {
        devices: [
          { name: 'Desktop', width: '' },
          { name: 'Tablet', width: '768px', widthMedia: '992px' },
          { name: 'Mobile', width: '320px', widthMedia: '480px' },
        ],
      },
      canvas: {
        styles: [
          'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap',
        ],
      },
      blockManager: {
        appendTo: '#blocks-container',
      },
      layerManager: {
        appendTo: '#layers-container',
      },
      styleManager: {
        appendTo: '#styles-container',
        sectors: [
          {
            name: 'General',
            open: true,
            properties: [
              { type: 'color', property: 'color', label: 'Color de texto' },
              { type: 'color', property: 'background-color', label: 'Color de fondo' },
            ],
          },
          {
            name: 'Dimensiones',
            open: false,
            properties: [
              { type: 'integer', property: 'width', label: 'Ancho', units: ['px', '%', 'em'] },
              { type: 'integer', property: 'height', label: 'Alto', units: ['px', '%', 'em'] },
              { type: 'integer', property: 'padding', label: 'Padding', units: ['px', 'em'] },
              { type: 'integer', property: 'margin', label: 'Margen', units: ['px', 'em'] },
            ],
          },
          {
            name: 'Tipografia',
            open: false,
            properties: [
              { type: 'select', property: 'font-family', label: 'Fuente', options: [
                { id: 'inter', value: 'Inter, sans-serif', name: 'Inter' },
                { id: 'arial', value: 'Arial, sans-serif', name: 'Arial' },
                { id: 'georgia', value: 'Georgia, serif', name: 'Georgia' },
              ]},
              { type: 'integer', property: 'font-size', label: 'Tamano', units: ['px', 'em', 'rem'] },
              { type: 'select', property: 'font-weight', label: 'Peso', options: [
                { id: 'normal', value: '400', name: 'Normal' },
                { id: 'medium', value: '500', name: 'Medium' },
                { id: 'semibold', value: '600', name: 'Semibold' },
                { id: 'bold', value: '700', name: 'Bold' },
              ]},
              { type: 'select', property: 'text-align', label: 'Alineacion', options: [
                { id: 'left', value: 'left', name: 'Izquierda' },
                { id: 'center', value: 'center', name: 'Centro' },
                { id: 'right', value: 'right', name: 'Derecha' },
              ]},
            ],
          },
          {
            name: 'Decoracion',
            open: false,
            properties: [
              { type: 'integer', property: 'border-radius', label: 'Bordes', units: ['px', '%'] },
              { type: 'color', property: 'border-color', label: 'Color borde' },
              { type: 'integer', property: 'border-width', label: 'Ancho borde', units: ['px'] },
            ],
          },
        ],
      },
    });

    // Add custom blocks
    addCustomBlocks(editor);

    // Load initial content if provided
    if (initialContent) {
      if (initialContent.components) {
        editor.setComponents(initialContent.components);
        editor.setStyle(initialContent.styles || '');
      } else if (initialContent.html) {
        editor.setComponents(initialContent.html);
        editor.setStyle(initialContent.css || '');
      }
    }

    // Setup auto-save on changes
    editor.on('update', () => {
      const data = {
        html: editor.getHtml(),
        css: editor.getCss() || '',
        components: JSON.parse(JSON.stringify(editor.getComponents())),
        styles: JSON.parse(JSON.stringify(editor.getStyle())),
      };
      onSaveRef.current(data);
    });

    // Enable click-to-add for blocks (not just drag)
    editor.on('block:drag:stop', (component: any) => {
      if (component) {
        editor.select(component);
      }
    });

    // Add blocks on single click (after editor fully loads)
    editor.on('load', () => {
      const blocksContainer = document.getElementById('blocks-container');
      if (blocksContainer) {
        blocksContainer.addEventListener('click', (e) => {
          const blockEl = (e.target as HTMLElement).closest('.gjs-block');
          if (blockEl) {
            // GrapesJS stores block id in title attribute or data-gjs-type
            const blockTitle = blockEl.getAttribute('title') || blockEl.querySelector('.gjs-block-label')?.textContent;
            // Find block by matching label
            const allBlocks = editor.BlockManager.getAll();
            const block = allBlocks.find((b: any) => b.get('label') === blockTitle);
            
            if (block) {
              const content = block.get('content');
              if (content) {
                try {
                  editor.addComponents(content);
                  // Directly call save callback after adding block
                  const data = {
                    html: editor.getHtml(),
                    css: editor.getCss() || '',
                    components: JSON.parse(JSON.stringify(editor.getComponents())),
                    styles: JSON.parse(JSON.stringify(editor.getStyle())),
                  };
                  onSaveRef.current(data);
                } catch (err) {
                  console.error('Error adding block:', err);
                }
              }
            }
          }
        });
      }
    });

    editorRef.current = editor;
    onLoad?.();
  }, [initialContent, onSave, onLoad]);

  useEffect(() => {
    initEditor();

    return () => {
      if (editorRef.current) {
        editorRef.current.destroy();
        editorRef.current = null;
      }
    };
  }, [initEditor]);

  return (
    <div className="flex h-full">
      <div id="gjs-container" ref={containerRef} className="flex-1 bg-white" />
    </div>
  );
}

function addCustomBlocks(editor: Editor) {
  const blockManager = editor.BlockManager;

  // Hero Section
  blockManager.add('hero-section', {
    label: 'Hero',
    category: 'Secciones',
    content: `
      <section style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 80px 40px; text-align: center; min-height: 500px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
        <h1 style="color: #ffffff; font-size: 48px; font-weight: 700; margin-bottom: 20px; font-family: Inter, sans-serif;">Bienvenido a tu sitio</h1>
        <p style="color: #a0aec0; font-size: 20px; max-width: 600px; margin-bottom: 32px; font-family: Inter, sans-serif;">Crea experiencias increibles para tus usuarios con nuestro constructor de paginas visual.</p>
        <div style="display: flex; gap: 16px; justify-content: center;">
          <button style="background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); color: white; padding: 14px 32px; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer;">Comenzar ahora</button>
          <button style="background: transparent; color: white; padding: 14px 32px; border: 2px solid rgba(255,255,255,0.3); border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer;">Saber mas</button>
        </div>
      </section>
    `,
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="2" y="4" width="20" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><line x1="6" y1="10" x2="18" y2="10" stroke="currentColor" stroke-width="2"/><line x1="8" y1="14" x2="16" y2="14" stroke="currentColor" stroke-width="2"/></svg>',
  });

  // Features Section
  blockManager.add('features-section', {
    label: 'Caracteristicas',
    category: 'Secciones',
    content: `
      <section style="background: #0f172a; padding: 80px 40px;">
        <h2 style="color: #ffffff; font-size: 36px; font-weight: 700; text-align: center; margin-bottom: 16px; font-family: Inter, sans-serif;">Nuestras Caracteristicas</h2>
        <p style="color: #94a3b8; font-size: 18px; text-align: center; margin-bottom: 48px; font-family: Inter, sans-serif;">Todo lo que necesitas para crear sitios increibles</p>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 32px; max-width: 1200px; margin: 0 auto;">
          <div style="background: #1e293b; padding: 32px; border-radius: 12px; text-align: center;">
            <div style="width: 64px; height: 64px; background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); border-radius: 12px; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; color: white; font-size: 28px;">1</div>
            <h3 style="color: #ffffff; font-size: 20px; font-weight: 600; margin-bottom: 12px; font-family: Inter, sans-serif;">Facil de usar</h3>
            <p style="color: #94a3b8; font-size: 14px; font-family: Inter, sans-serif;">Interfaz intuitiva que cualquiera puede dominar en minutos.</p>
          </div>
          <div style="background: #1e293b; padding: 32px; border-radius: 12px; text-align: center;">
            <div style="width: 64px; height: 64px; background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); border-radius: 12px; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; color: white; font-size: 28px;">2</div>
            <h3 style="color: #ffffff; font-size: 20px; font-weight: 600; margin-bottom: 12px; font-family: Inter, sans-serif;">Totalmente responsive</h3>
            <p style="color: #94a3b8; font-size: 14px; font-family: Inter, sans-serif;">Tus paginas se veran perfectas en cualquier dispositivo.</p>
          </div>
          <div style="background: #1e293b; padding: 32px; border-radius: 12px; text-align: center;">
            <div style="width: 64px; height: 64px; background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); border-radius: 12px; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; color: white; font-size: 28px;">3</div>
            <h3 style="color: #ffffff; font-size: 20px; font-weight: 600; margin-bottom: 12px; font-family: Inter, sans-serif;">Altamente personalizable</h3>
            <p style="color: #94a3b8; font-size: 14px; font-family: Inter, sans-serif;">Personaliza cada detalle para que coincida con tu marca.</p>
          </div>
        </div>
      </section>
    `,
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="2" y="3" width="6" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="2"/><rect x="9" y="3" width="6" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="2"/><rect x="16" y="3" width="6" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  });

  // Testimonials Section
  blockManager.add('testimonials-section', {
    label: 'Testimonios',
    category: 'Secciones',
    content: `
      <section style="background: #1e293b; padding: 80px 40px;">
        <h2 style="color: #ffffff; font-size: 36px; font-weight: 700; text-align: center; margin-bottom: 48px; font-family: Inter, sans-serif;">Lo que dicen nuestros clientes</h2>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 32px; max-width: 900px; margin: 0 auto;">
          <div style="background: #0f172a; padding: 32px; border-radius: 12px; border-left: 4px solid #e07a3c;">
            <p style="color: #e2e8f0; font-size: 16px; font-style: italic; margin-bottom: 20px; font-family: Inter, sans-serif;">"Esta herramienta ha transformado completamente como creamos nuestras landing pages. Increiblemente facil y potente."</p>
            <div style="display: flex; align-items: center; gap: 12px;">
              <div style="width: 48px; height: 48px; background: #e07a3c; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-weight: 600;">MC</div>
              <div>
                <p style="color: #ffffff; font-weight: 600; font-size: 14px; margin: 0; font-family: Inter, sans-serif;">Maria Castro</p>
                <p style="color: #94a3b8; font-size: 12px; margin: 0; font-family: Inter, sans-serif;">CEO, TechStart</p>
              </div>
            </div>
          </div>
          <div style="background: #0f172a; padding: 32px; border-radius: 12px; border-left: 4px solid #e07a3c;">
            <p style="color: #e2e8f0; font-size: 16px; font-style: italic; margin-bottom: 20px; font-family: Inter, sans-serif;">"El mejor constructor de paginas que hemos usado. Nuestro equipo de marketing ahora puede crear paginas sin ayuda tecnica."</p>
            <div style="display: flex; align-items: center; gap: 12px;">
              <div style="width: 48px; height: 48px; background: #e07a3c; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-weight: 600;">JR</div>
              <div>
                <p style="color: #ffffff; font-weight: 600; font-size: 14px; margin: 0; font-family: Inter, sans-serif;">Juan Rodriguez</p>
                <p style="color: #94a3b8; font-size: 12px; margin: 0; font-family: Inter, sans-serif;">Director de Marketing</p>
              </div>
            </div>
          </div>
        </div>
      </section>
    `,
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 17c2-2 2-4 0-6s-2-4 0-6" stroke="currentColor" stroke-width="2" fill="none"/><path d="M18 17c2-2 2-4 0-6s-2-4 0-6" stroke="currentColor" stroke-width="2" fill="none"/></svg>',
  });

  // Pricing Section
  blockManager.add('pricing-section', {
    label: 'Precios',
    category: 'Secciones',
    content: `
      <section style="background: #0f172a; padding: 80px 40px;">
        <h2 style="color: #ffffff; font-size: 36px; font-weight: 700; text-align: center; margin-bottom: 16px; font-family: Inter, sans-serif;">Planes y Precios</h2>
        <p style="color: #94a3b8; font-size: 18px; text-align: center; margin-bottom: 48px; font-family: Inter, sans-serif;">Elige el plan perfecto para tu negocio</p>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 32px; max-width: 1100px; margin: 0 auto;">
          <div style="background: #1e293b; padding: 32px; border-radius: 16px; text-align: center;">
            <h3 style="color: #94a3b8; font-size: 16px; font-weight: 600; margin-bottom: 8px; font-family: Inter, sans-serif;">BASICO</h3>
            <div style="color: #ffffff; font-size: 48px; font-weight: 700; margin-bottom: 8px; font-family: Inter, sans-serif;">$29</div>
            <p style="color: #64748b; font-size: 14px; margin-bottom: 24px; font-family: Inter, sans-serif;">por mes</p>
            <ul style="list-style: none; padding: 0; margin-bottom: 32px; text-align: left;">
              <li style="color: #e2e8f0; font-size: 14px; padding: 8px 0; border-bottom: 1px solid #334155; font-family: Inter, sans-serif;">5 paginas</li>
              <li style="color: #e2e8f0; font-size: 14px; padding: 8px 0; border-bottom: 1px solid #334155; font-family: Inter, sans-serif;">Plantillas basicas</li>
              <li style="color: #e2e8f0; font-size: 14px; padding: 8px 0; font-family: Inter, sans-serif;">Soporte por email</li>
            </ul>
            <button style="width: 100%; background: #334155; color: white; padding: 14px; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer;">Elegir plan</button>
          </div>
          <div style="background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); padding: 32px; border-radius: 16px; text-align: center; transform: scale(1.05);">
            <h3 style="color: rgba(255,255,255,0.8); font-size: 16px; font-weight: 600; margin-bottom: 8px; font-family: Inter, sans-serif;">PROFESIONAL</h3>
            <div style="color: #ffffff; font-size: 48px; font-weight: 700; margin-bottom: 8px; font-family: Inter, sans-serif;">$79</div>
            <p style="color: rgba(255,255,255,0.7); font-size: 14px; margin-bottom: 24px; font-family: Inter, sans-serif;">por mes</p>
            <ul style="list-style: none; padding: 0; margin-bottom: 32px; text-align: left;">
              <li style="color: #ffffff; font-size: 14px; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.2); font-family: Inter, sans-serif;">Paginas ilimitadas</li>
              <li style="color: #ffffff; font-size: 14px; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.2); font-family: Inter, sans-serif;">Todas las plantillas</li>
              <li style="color: #ffffff; font-size: 14px; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.2); font-family: Inter, sans-serif;">Soporte prioritario</li>
              <li style="color: #ffffff; font-size: 14px; padding: 8px 0; font-family: Inter, sans-serif;">Analiticas avanzadas</li>
            </ul>
            <button style="width: 100%; background: white; color: #e07a3c; padding: 14px; border: none; border-radius: 8px; font-size: 16px; font-weight: 700; cursor: pointer;">Elegir plan</button>
          </div>
          <div style="background: #1e293b; padding: 32px; border-radius: 16px; text-align: center;">
            <h3 style="color: #94a3b8; font-size: 16px; font-weight: 600; margin-bottom: 8px; font-family: Inter, sans-serif;">EMPRESA</h3>
            <div style="color: #ffffff; font-size: 48px; font-weight: 700; margin-bottom: 8px; font-family: Inter, sans-serif;">$199</div>
            <p style="color: #64748b; font-size: 14px; margin-bottom: 24px; font-family: Inter, sans-serif;">por mes</p>
            <ul style="list-style: none; padding: 0; margin-bottom: 32px; text-align: left;">
              <li style="color: #e2e8f0; font-size: 14px; padding: 8px 0; border-bottom: 1px solid #334155; font-family: Inter, sans-serif;">Todo en Profesional</li>
              <li style="color: #e2e8f0; font-size: 14px; padding: 8px 0; border-bottom: 1px solid #334155; font-family: Inter, sans-serif;">API personalizada</li>
              <li style="color: #e2e8f0; font-size: 14px; padding: 8px 0; border-bottom: 1px solid #334155; font-family: Inter, sans-serif;">Manager dedicado</li>
              <li style="color: #e2e8f0; font-size: 14px; padding: 8px 0; font-family: Inter, sans-serif;">SLA garantizado</li>
            </ul>
            <button style="width: 100%; background: #334155; color: white; padding: 14px; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer;">Contactar</button>
          </div>
        </div>
      </section>
    `,
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><text x="12" y="16" text-anchor="middle" font-size="10" fill="currentColor">$</text></svg>',
  });

  // Team Section
  blockManager.add('team-section', {
    label: 'Equipo',
    category: 'Secciones',
    content: `
      <section style="background: #1e293b; padding: 80px 40px;">
        <h2 style="color: #ffffff; font-size: 36px; font-weight: 700; text-align: center; margin-bottom: 16px; font-family: Inter, sans-serif;">Nuestro Equipo</h2>
        <p style="color: #94a3b8; font-size: 18px; text-align: center; margin-bottom: 48px; font-family: Inter, sans-serif;">Conoce a las personas detras del proyecto</p>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 32px; max-width: 1100px; margin: 0 auto;">
          <div style="text-align: center;">
            <div style="width: 120px; height: 120px; background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); border-radius: 50%; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; color: white; font-size: 36px; font-weight: 600;">AG</div>
            <h3 style="color: #ffffff; font-size: 18px; font-weight: 600; margin-bottom: 4px; font-family: Inter, sans-serif;">Ana Garcia</h3>
            <p style="color: #e07a3c; font-size: 14px; margin-bottom: 8px; font-family: Inter, sans-serif;">CEO & Fundadora</p>
            <p style="color: #94a3b8; font-size: 13px; font-family: Inter, sans-serif;">Visionaria con 10+ anos en tecnologia</p>
          </div>
          <div style="text-align: center;">
            <div style="width: 120px; height: 120px; background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); border-radius: 50%; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; color: white; font-size: 36px; font-weight: 600;">CM</div>
            <h3 style="color: #ffffff; font-size: 18px; font-weight: 600; margin-bottom: 4px; font-family: Inter, sans-serif;">Carlos Martinez</h3>
            <p style="color: #e07a3c; font-size: 14px; margin-bottom: 8px; font-family: Inter, sans-serif;">CTO</p>
            <p style="color: #94a3b8; font-size: 13px; font-family: Inter, sans-serif;">Experto en arquitectura de software</p>
          </div>
          <div style="text-align: center;">
            <div style="width: 120px; height: 120px; background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); border-radius: 50%; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; color: white; font-size: 36px; font-weight: 600;">LP</div>
            <h3 style="color: #ffffff; font-size: 18px; font-weight: 600; margin-bottom: 4px; font-family: Inter, sans-serif;">Laura Perez</h3>
            <p style="color: #e07a3c; font-size: 14px; margin-bottom: 8px; font-family: Inter, sans-serif;">Directora de Diseno</p>
            <p style="color: #94a3b8; font-size: 13px; font-family: Inter, sans-serif;">Apasionada por el UX/UI</p>
          </div>
          <div style="text-align: center;">
            <div style="width: 120px; height: 120px; background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); border-radius: 50%; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; color: white; font-size: 36px; font-weight: 600;">DR</div>
            <h3 style="color: #ffffff; font-size: 18px; font-weight: 600; margin-bottom: 4px; font-family: Inter, sans-serif;">Diego Ramirez</h3>
            <p style="color: #e07a3c; font-size: 14px; margin-bottom: 8px; font-family: Inter, sans-serif;">Lead Developer</p>
            <p style="color: #94a3b8; font-size: 13px; font-family: Inter, sans-serif;">Full-stack con amor por React</p>
          </div>
        </div>
      </section>
    `,
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="7" r="3" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="15" cy="7" r="3" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 21v-2a4 4 0 014-4h4a4 4 0 014 4v2" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  });

  // Contact Section
  blockManager.add('contact-section', {
    label: 'Contacto',
    category: 'Secciones',
    content: `
      <section style="background: #0f172a; padding: 80px 40px;">
        <div style="max-width: 600px; margin: 0 auto; text-align: center;">
          <h2 style="color: #ffffff; font-size: 36px; font-weight: 700; margin-bottom: 16px; font-family: Inter, sans-serif;">Contactanos</h2>
          <p style="color: #94a3b8; font-size: 18px; margin-bottom: 40px; font-family: Inter, sans-serif;">Estamos aqui para ayudarte. Envianos un mensaje.</p>
          <form style="display: flex; flex-direction: column; gap: 20px;">
            <input type="text" placeholder="Nombre completo" style="background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px 16px; color: #ffffff; font-size: 16px; font-family: Inter, sans-serif;" />
            <input type="email" placeholder="Email" style="background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px 16px; color: #ffffff; font-size: 16px; font-family: Inter, sans-serif;" />
            <textarea placeholder="Tu mensaje" rows="4" style="background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px 16px; color: #ffffff; font-size: 16px; resize: none; font-family: Inter, sans-serif;"></textarea>
            <button type="submit" style="background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); color: white; padding: 16px 32px; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer;">Enviar mensaje</button>
          </form>
        </div>
      </section>
    `,
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="2" y="4" width="20" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M22 6l-10 7L2 6" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  });

  // Basic elements
  blockManager.add('text-block', {
    label: 'Texto',
    category: 'Basicos',
    content: '<p style="color: #e2e8f0; font-size: 16px; font-family: Inter, sans-serif;">Escribe tu texto aqui...</p>',
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><text x="3" y="18" font-size="16" fill="currentColor">T</text></svg>',
  });

  blockManager.add('heading-block', {
    label: 'Titulo',
    category: 'Basicos',
    content: '<h2 style="color: #ffffff; font-size: 32px; font-weight: 700; font-family: Inter, sans-serif;">Tu titulo aqui</h2>',
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><text x="3" y="18" font-size="18" font-weight="bold" fill="currentColor">H</text></svg>',
  });

  blockManager.add('button-block', {
    label: 'Boton',
    category: 'Basicos',
    content: '<button style="background: linear-gradient(135deg, #e07a3c 0%, #d96830 100%); color: white; padding: 14px 28px; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; font-family: Inter, sans-serif;">Click aqui</button>',
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="8" width="18" height="8" rx="4" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  });

  blockManager.add('image-block', {
    label: 'Imagen',
    category: 'Basicos',
    content: '<img src="https://via.placeholder.com/400x300/1e293b/e07a3c?text=Tu+Imagen" style="max-width: 100%; border-radius: 8px;" />',
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="18" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="8.5" cy="8.5" r="1.5" fill="currentColor"/><path d="M21 15l-5-5L5 21" stroke="currentColor" stroke-width="2" fill="none"/></svg>',
  });

  blockManager.add('divider-block', {
    label: 'Separador',
    category: 'Basicos',
    content: '<hr style="border: none; border-top: 1px solid #334155; margin: 32px 0;" />',
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><line x1="2" y1="12" x2="22" y2="12" stroke="currentColor" stroke-width="2"/></svg>',
  });

  blockManager.add('columns-block', {
    label: '2 Columnas',
    category: 'Layout',
    content: `
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 32px; padding: 32px;">
        <div style="background: #1e293b; padding: 24px; border-radius: 8px; min-height: 150px;">
          <p style="color: #94a3b8; font-family: Inter, sans-serif;">Columna 1</p>
        </div>
        <div style="background: #1e293b; padding: 24px; border-radius: 8px; min-height: 150px;">
          <p style="color: #94a3b8; font-family: Inter, sans-serif;">Columna 2</p>
        </div>
      </div>
    `,
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="2" y="4" width="9" height="16" fill="none" stroke="currentColor" stroke-width="2"/><rect x="13" y="4" width="9" height="16" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  });

  blockManager.add('container-block', {
    label: 'Contenedor',
    category: 'Layout',
    content: '<div style="background: #1e293b; padding: 40px; border-radius: 12px; min-height: 200px;"><p style="color: #94a3b8; font-family: Inter, sans-serif;">Arrastra elementos aqui</p></div>',
    media: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="18" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="4 2"/></svg>',
  });
}

export default GrapesEditor;
