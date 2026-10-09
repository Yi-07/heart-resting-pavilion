// 素材目录单源(frontend-plan §5.1 预留的 asset 层):id → 语义标签 + SVG loader。
// 语义标签给后端 LLM 选材清单用(投影生成,不双单源);loader 给渲染器内联用(?raw 静态导入)。
// 新增素材:SVG 放 assets/icons/<id>.svg → 此处登记 → 标签取 asset-candidates.md 同名条目。

import overwhelmedPersonDesk from './assets/icons/overwhelmed-person-desk.svg?raw'
import studyingLateLamp from './assets/icons/studying-late-lamp.svg?raw'
import laptopDesk from './assets/icons/laptop-desk.svg?raw'
import deskCluttered from './assets/icons/desk-cluttered.svg?raw'
import desk from './assets/icons/desk.svg?raw'
import stormCloud from './assets/icons/storm-cloud.svg?raw'
import rainCloudDrops from './assets/icons/rain-cloud-drops.svg?raw'
import personAloneRoom from './assets/icons/person-alone-room.svg?raw'
import volcano from './assets/icons/volcano.svg?raw'
import scrollingPhone from './assets/icons/scrolling-phone.svg?raw'
import rowFiguresDifferentHeights from './assets/icons/row-figures-different-heights.svg?raw'
import crossroads from './assets/icons/crossroads.svg?raw'
import mirror from './assets/icons/mirror.svg?raw'
import bathroomScale from './assets/icons/bathroom-scale.svg?raw'
import startlingAwake from './assets/icons/startling-awake.svg?raw'
import singleFigureBesideCrowd from './assets/icons/single-figure-beside-crowd.svg?raw'
import crowdPeople from './assets/icons/crowd-people.svg?raw'
import twoHearts from './assets/icons/two-hearts.svg?raw'
import heartCrack from './assets/icons/heart-crack.svg?raw'
import armchair from './assets/icons/armchair.svg?raw'
import hotDrinkMugSteaming from './assets/icons/hot-drink-mug-steaming.svg?raw'
import readingArmchair from './assets/icons/reading-armchair.svg?raw'
import catCurledUp from './assets/icons/cat-curled-up.svg?raw'
import fireplace from './assets/icons/fireplace.svg?raw'
import houseNightLights from './assets/icons/house-night-lights.svg?raw'
import openBook from './assets/icons/open-book.svg?raw'
import magnifyingGlass from './assets/icons/magnifying-glass.svg?raw'
import quillInk from './assets/icons/quill-ink.svg?raw'
import personReadingHugeOpen from './assets/icons/person-reading-huge-open.svg?raw'
import candleLit from './assets/icons/candle-lit.svg?raw'
import lighthouseBeam from './assets/icons/lighthouse-beam.svg?raw'
import parachuteOpening from './assets/icons/parachute-opening.svg?raw'
import holdingHand from './assets/icons/holding-hand.svg?raw'
import personCatchingAnotherFalling from './assets/icons/person-catching-another-falling.svg?raw'
import twoPeopleHoldingUmbrella from './assets/icons/two-people-holding-umbrella.svg?raw'

/** 素材条目:渲染器消费 loader;后端选材清单消费 id+tags 投影 */
export interface AssetEntry {
  /** 图标 id,如 'person.exhausted'——dot 前缀=族(板式 iconPool 约束用) */
  id: string
  /** 语义标签(给 LLM 选材;中文短语) */
  tags: string[]
  /** ?raw 导入的 SVG 原文 */
  loader: () => string
}

export const ASSET_MANIFESTS: Record<string, AssetEntry> = {
  'desk.overwhelmed': { id: 'desk.overwhelmed', tags: ['被压垮', '桌前', '职场过载', '学业'], loader: () => overwhelmedPersonDesk },
  'desk.studying-late': { id: 'desk.studying-late', tags: ['深夜', '台灯', '学习', '学业焦虑'], loader: () => studyingLateLamp },
  'desk.laptop': { id: 'desk.laptop', tags: ['电脑', '书桌', '工作'], loader: () => laptopDesk },
  'desk.cluttered': { id: 'desk.cluttered', tags: ['杂乱', '文件堆', '任务多'], loader: () => deskCluttered },
  'desk.plain': { id: 'desk.plain', tags: ['书桌', '基线'], loader: () => desk },
  'state.storm-cloud': { id: 'state.storm-cloud', tags: ['乌云', '焦虑', '压力大'], loader: () => stormCloud },
  'state.rain-cloud': { id: 'state.rain-cloud', tags: ['雨云', '低落', '流泪'], loader: () => rainCloudDrops },
  'state.alone-room': { id: 'state.alone-room', tags: ['孤独', '空房间', '一个人'], loader: () => personAloneRoom },
  'state.volcano': { id: 'state.volcano', tags: ['火山', '愤怒', '爆发'], loader: () => volcano },
  'state.scrolling-phone': { id: 'state.scrolling-phone', tags: ['刷手机', '拖延', '失眠'], loader: () => scrollingPhone },
  'self.compare-figures': { id: 'self.compare-figures', tags: ['比较', '高低', '自我怀疑'], loader: () => rowFiguresDifferentHeights },
  'self.crossroads': { id: 'self.crossroads', tags: ['十字路口', '迷茫', '选择'], loader: () => crossroads },
  'self.mirror': { id: 'self.mirror', tags: ['镜子', '身体形象', '自我审视'], loader: () => mirror },
  'self.scale': { id: 'self.scale', tags: ['体重秤', '身材焦虑', '身体形象'], loader: () => bathroomScale },
  'self.startling-awake': { id: 'self.startling-awake', tags: ['惊醒', '失眠', '夜里醒'], loader: () => startlingAwake },
  'rel.alone-in-crowd': { id: 'rel.alone-in-crowd', tags: ['聚会孤独', '人群边缘', '社交'], loader: () => singleFigureBesideCrowd },
  'rel.crowd': { id: 'rel.crowd', tags: ['人群', '热闹', '聚会'], loader: () => crowdPeople },
  'rel.two-hearts': { id: 'rel.two-hearts', tags: ['恋爱', '两颗心', '亲密'], loader: () => twoHearts },
  'rel.heart-crack': { id: 'rel.heart-crack', tags: ['失恋', '心碎', '裂痕'], loader: () => heartCrack },
  'rel.empty-armchair': { id: 'rel.empty-armchair', tags: ['空椅', '丧失', '故人空位'], loader: () => armchair },
  'warm.mug': { id: 'warm.mug', tags: ['热饮', '安心', '捧杯'], loader: () => hotDrinkMugSteaming },
  'warm.reading-armchair': { id: 'warm.reading-armchair', tags: ['看书', '闲适', '扶手椅'], loader: () => readingArmchair },
  'warm.cat': { id: 'warm.cat', tags: ['猫', '打盹', '陪伴'], loader: () => catCurledUp },
  'warm.fireplace': { id: 'warm.fireplace', tags: ['壁炉', '炉火', '屋里暖'], loader: () => fireplace },
  'warm.house-night': { id: 'warm.house-night', tags: ['家', '亮灯', '有人在等'], loader: () => houseNightLights },
  'read.open-book': { id: 'read.open-book', tags: ['书', '科普', '阅读'], loader: () => openBook },
  'read.magnifier': { id: 'read.magnifier', tags: ['放大镜', '求证', '细看'], loader: () => magnifyingGlass },
  'read.quill': { id: 'read.quill', tags: ['羽毛笔', '记录', '思考'], loader: () => quillInk },
  'read.big-book': { id: 'read.big-book', tags: ['读大书', '投入', '钻研'], loader: () => personReadingHugeOpen },
  'read.candle': { id: 'read.candle', tags: ['蜡烛', '安静', '沉思'], loader: () => candleLit },
  'crisis.lighthouse': { id: 'crisis.lighthouse', tags: ['灯塔', '照引', '风暴中'], loader: () => lighthouseBeam },
  'crisis.parachute': { id: 'crisis.parachute', tags: ['降落伞', '被接住', '托底'], loader: () => parachuteOpening },
  'crisis.holding-hand': { id: 'crisis.holding-hand', tags: ['牵手', '握住', '陪伴'], loader: () => holdingHand },
  'crisis.catching': { id: 'crisis.catching', tags: ['接住', '拉一把', '支撑'], loader: () => personCatchingAnotherFalling },
  'crisis.umbrella': { id: 'crisis.umbrella', tags: ['共伞', '一起挡雨', '不孤单'], loader: () => twoPeopleHoldingUmbrella },
}

/** 取 SVG 原文;未知 id 记 WARN 返回 null(渲染器跳过兜底,双保险) */
export function assetSvg(id: string): string | null {
  const entry = ASSET_MANIFESTS[id]
  if (entry === undefined) return null
  return entry.loader()
}
