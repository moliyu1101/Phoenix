"use client";
export {PageFrame} from "./PhoenixPageFrame";
export {ConfigurationPage as SettingsPage} from "./PhoenixConfiguration";
export {KnowledgeWorkspace as KnowledgePage} from "./workspace/KnowledgeWorkspace";
export {MemoryWorkspace as MemoryPage} from "./workspace/MemoryWorkspace";
export {EvolutionWorkspace as EvolutionPage} from "./workspace/EvolutionWorkspace";
import {ConfigurationPage} from "./PhoenixConfiguration";
export function SwarmPage(){return <ConfigurationPage roster/>;}
