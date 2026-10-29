import React, { useEffect, useRef } from "react";
import { useAppDispatch, useAppSelector } from "../../redux/hooks";
import "../../assets/css/MindMap.css";
import jsMind from "jsmind";
import "jsmind/style/jsmind.css";
import {
  mindmapFailed as uiMindmapFailed,
  mindmapImageDone as uiMindmapImageDone,
} from "../../redux/slices/uiSlice";

import {
  setRendered,
  setGenerationTime,
  setError,
} from "../../redux/slices/mindmapSlice";

import { useTranslation } from "react-i18next";
import { useFeatureConfig } from "../../hooks/useFeatureConfig";

declare global {
  interface Window {
    jsMind: any;
  }
}

const sanitizeNode = (node: any, fallbackIndex: number = 0, seen = new Set<string>()): any => {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return null;

  // Recover id from typo keys like "id:", "id：", " id", "Id"
  let id = node.id;
  if (!id || typeof id !== 'string') {
    const candidateKeys = Object.keys(node).filter(
      k => /^[\s]*id[\s:：.]*$/i.test(k) && k !== 'id'
    );
    const candidate = candidateKeys.length ? node[candidateKeys[0]] : null;
    id = (candidate && typeof candidate === 'string') ? candidate : `node_${fallbackIndex}_${Date.now()}`;
  }
  id = id.trim();

  // Deduplicate ids — jsMind requires unique ids across the tree
  if (seen.has(id)) {
    id = `${id}_dup_${fallbackIndex}`;
  }
  seen.add(id);

  // Recover topic from typo keys like "topic:", "Topic", "label", "text", "name"
  let topic = node.topic;
  if (!topic || typeof topic !== 'string') {
    const topicAliases = Object.keys(node).find(
      k => /^[\s]*(topic[\s:：.]*|label|text|title|name)[\s]*$/i.test(k) && k !== 'topic'
    );
    const candidate = topicAliases ? node[topicAliases] : null;
    topic = (candidate && typeof candidate === 'string') ? candidate : id;
  }
  topic = topic.trim() || id;

  // Truncate excessively long topics that break rendering
  if (topic.length > 200) {
    topic = topic.slice(0, 197) + '...';
  }

  const sanitized: any = { id, topic };

  // Preserve direction if present (left/right for jsMind layout)
  if (node.direction && typeof node.direction === 'string') {
    sanitized.direction = node.direction;
  }

  // Recover children from typo keys like "children:", "child", "nodes", "sub"
  let children = node.children;
  if (!Array.isArray(children)) {
    const childAliases = Object.keys(node).find(
      k => /^[\s]*(children[\s:：.]*|child|nodes|sub|subtopics)[\s]*$/i.test(k) && k !== 'children'
    );
    children = childAliases ? node[childAliases] : undefined;
  }

  if (Array.isArray(children)) {
    sanitized.children = children
      .map((child: any, i: number) => sanitizeNode(child, i, seen))
      .filter(Boolean);
  }

  return sanitized;
};

const validateJsMindData = (data: any): boolean => {
  try {
    if (!data || typeof data !== 'object') return false;
    if (!data.meta || !data.format || !data.data) return false;
    if (data.format !== 'node_tree') return false;
    if (!data.data.id || !data.data.topic) return false;
    data.data = sanitizeNode(data.data);
    return true;
  } catch (error) {
    return false;
  }
};

/** Extracts the first balanced {...} block from a string. */
const extractFirstJsonObject = (text: string): string | null => {
  const start = text.indexOf("{");
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (escape) { escape = false; continue; }
    if (ch === "\\" && inString) { escape = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
};

const tryParse = (s: string): any | null => {
  try {
    const p = JSON.parse(s);
    if (validateJsMindData(p)) return p;
  } catch {}
  return null;
};

const cleanJsMindContent = (content: string): any => {
  if (!content || !content.trim()) {
    return {
      "meta": { "name": "default", "author": "ai_assistant", "version": "1.0" },
      "format": "node_tree",
      "data": { "id": "root", "topic": "Main Topic", "children": [] }
    };
  }

  // Strategy 1: direct parse (handles clean JSON returned by backend)
  let result = tryParse(content.trim());
  if (result) return result;

  // Strategy 2: strip code fences then direct parse
  const stripped = content.replace(/```[a-zA-Z]*\n?([\s\S]*?)```/gs, "$1").trim();
  result = tryParse(stripped);
  if (result) return result;

  // Strategy 3: balanced-brace extractor on stripped content
  const extracted1 = extractFirstJsonObject(stripped);
  if (extracted1) {
    result = tryParse(extracted1);
    if (result) return result;
  }

  // Strategy 4: balanced-brace extractor on raw content (fallback if fence-strip corrupted it)
  const extracted2 = extractFirstJsonObject(content);
  if (extracted2) {
    result = tryParse(extracted2);
    if (result) return result;
  }

  console.error("cleanJsMindContent: all strategies failed. Raw content preview:", content.slice(0, 200));
  throw new Error("INVALID_FORMAT");
};

// Renders the mind map the pipeline fetched into the store (see
// redux/useAudioPipeline), and — because both need the rendered DOM — takes the
// screenshot the report embeds. The fetch is not owned here: this tab is
// unmounted whenever another tab is selected, so a mind map may already be in
// the store by the time it first mounts.
const MindMapTab: React.FC = () => {
  const { t } = useTranslation();
  const dispatch = useAppDispatch();
  const { guard: featureGuard } = useFeatureConfig();

  const sessionId = useAppSelector((s) => s.ui.sessionId);

  const { finalText, isRendered, startedAt, sessionId: mindmapSessionId } = useAppSelector((s) => s.mindmap);

  const jsmindRef = useRef<HTMLDivElement>(null);
  const jsmindInstance = useRef<any>(null);
  const isInitializedRef = useRef(false);
  // Ensures the screenshot is captured/uploaded (and the session marked complete)
  // exactly once per session, even though renderMindmap re-runs on tab re-mounts.
  const capturedRef = useRef(false);

  const mindmapSessionIdRef = useRef<string | null>(null);
  mindmapSessionIdRef.current = mindmapSessionId ?? null;

  const cleanupJsMind = () => {
    try {
      if (jsmindInstance.current) {
        if (typeof jsmindInstance.current.remove === 'function') {
          jsmindInstance.current.remove();
        } else if (typeof jsmindInstance.current.destroy === 'function') {
          jsmindInstance.current.destroy();
        } else if (typeof jsmindInstance.current.clear === 'function') {
          jsmindInstance.current.clear();
        }
        jsmindInstance.current = null;
      }
      
      if (jsmindRef.current) {
        jsmindRef.current.innerHTML = '';
      }
    } catch (error) {
      console.warn('Error during jsMind cleanup:', error);
      if (jsmindRef.current) {
        jsmindRef.current.innerHTML = '';
      }
      jsmindInstance.current = null;
    }
  };

  useEffect(() => {
    if (!window.jsMind) {
      window.jsMind = jsMind;
    }
  }, []);

  useEffect(() => {
    if (!finalText || !jsmindRef.current) return;
    if (isRendered && !isInitializedRef.current) {
      renderMindmap();
      return;
    }
    if (!isRendered) {
      renderMindmap();
    }
  }, [finalText, isRendered]);

  const renderMindmap = async () => {
    let isInvalidFormat = false;
    
    try {
      let attempts = 0;
      while (!window.jsMind && attempts < 50) {
        await new Promise(resolve => setTimeout(resolve, 100));
        attempts++;
      }

      if (!window.jsMind) {
        throw new Error("jsMind library not loaded");
      }

      let mindData;
      try {
        mindData = cleanJsMindContent(finalText || ' ');
      } catch (error: any) {
        if (error.message === "INVALID_FORMAT") {
          isInvalidFormat = true;
          mindData = {
            "meta": {
              "name": "error_fallback",
              "author": "ai_assistant", 
              "version": "1.0"
            },
            "format": "node_tree",
            // Rendered in place of the mind map, so both topics are translated.
            "data": {
              "id": "root",
              "topic": t("mindmap.invalidFormatTitle"),
              "children": [
                {
                  "id": "error_msg",
                  "topic": t("mindmap.invalidFormatDetail")
                }
              ]
            }
          };
        } else {
          throw error;
        }
      }
      cleanupJsMind();
      const options = {
        container: jsmindRef.current,
        theme: 'primary',
        editable: true,
        mode: 'full',
        view: {
          engine: 'svg',
          hmargin: 120,        
          vmargin: 60,         
          line_width: 2,
          line_color: '#555',  
          draggable: true,
          hide_scrollbars_when_draggable: false,
          line_style: 'curved',
          node_overflow: 'wrap', 
          expander_style: 'char'
        },
      };

      jsmindInstance.current = new window.jsMind(options);
      jsmindInstance.current.show(mindData);

      isInitializedRef.current = true;

      // Measured from where the fetch was kicked off (useAudioPipeline) through
      // to this first render.
      if (startedAt && !isRendered) {
        dispatch(setGenerationTime(performance.now() - startedAt));
      }

      if (!isRendered) {
        dispatch(setRendered(true));
      }
      if (isInvalidFormat) {
        dispatch(setError("MindMap generation failed due to invalid format"));
        dispatch(uiMindmapFailed());
      } else {
        dispatch(uiMindmapImageDone());
      }

    } catch (error: any) {
      console.error("❌ jsMind render error:", error);

      dispatch(setError("Mindmap rendering failed"));
      dispatch(setRendered(true));
      dispatch(uiMindmapFailed());
    }
  };

  useEffect(() => {
    isInitializedRef.current = false;
    capturedRef.current = false;
  }, [sessionId]);

  useEffect(() => {
    return () => {
      cleanupJsMind();
      isInitializedRef.current = false;
    };
  }, []);

  return (
    <div className="mindmap-tab-fullscreen">
      <div className="mindmap-wrapper-fullscreen">
        <div className="mindmap-content-fullscreen">
          <div 
            ref={jsmindRef} 
            className="jsmind-container-fullscreen"
          />
        </div>
      </div>
    </div>
  );
};

export default MindMapTab;