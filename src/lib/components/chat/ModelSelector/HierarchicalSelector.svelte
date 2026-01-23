<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { marked } from 'marked';
	import Fuse from 'fuse.js';

	import dayjs from '$lib/dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import Spinner from '$lib/components/common/Spinner.svelte';
	import { flyAndScale } from '$lib/utils/transitions';
	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';
	import { goto } from '$app/navigation';

	import { deleteModel, getOllamaVersion, pullModel, unloadModel } from '$lib/apis/ollama';

	import {
		user,
		MODEL_DOWNLOAD_POOL,
		models,
		mobile,
		temporaryChatEnabled,
		settings,
		config
	} from '$lib/stores';
	import { toast } from 'svelte-sonner';
	import { capitalizeFirstLetter, sanitizeResponseContent, splitStream } from '$lib/utils';
	import { getModels } from '$lib/apis';

	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import ChatBubbleOval from '$lib/components/icons/ChatBubbleOval.svelte';

	import ModelItem from './ModelItem.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let id = '';
	export let value = '';
	export let placeholder = $i18n.t('Select a model');
	export let searchEnabled = true;
	export let searchPlaceholder = $i18n.t('Search a model');

	export let items: {
		label: string;
		value: string;
		model: any;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		[key: string]: any;
	}[] = [];

	export let className = 'w-[32rem]';
	export let triggerClassName = 'text-lg';

	export let pinModelHandler: (modelId: string) => void = () => {};

	let show = false;
	let selectedTag: string | null = null;

	let selectedModel: any = '';
	$: selectedModel = items.find((item) => item.value === value) ?? '';

	let searchValue = '';
	let ollamaVersion: any = null;
	let selectedModelIdx = 0;

	// Quando a pesquisa muda, desselecionar a tag
	$: if (searchValue) {
		selectedTag = null;
	}

	// Agrupar modelos por tags
	interface TagGroup {
		tag: string;
		models: typeof items;
		icon: string;
	}

	let tagGroups: TagGroup[] = [];

	// Tags especiais (usam valores fixos internos)
	const SPECIAL_TAG_OTHER = '__other__';
	const SPECIAL_TAG_ASSISTANT = '__assistant__';

	$: {
		// Agrupar modelos por tags
		const tagMap = new Map<string, TagGroup>();

		items
			.filter((item) => !(item.model?.info?.meta?.hidden ?? false))
			.forEach((item) => {
				const modelTags = item.model?.tags ?? [];

				// Se o modelo tem tags, adicionar a cada grupo de tag
				if (modelTags.length > 0) {
					modelTags.forEach((tag: any) => {
						let tagName = tag.name;

						// Detectar tag especial "assistant" e converter para valor interno
						if (tagName.toLowerCase() === 'assistant') {
							tagName = SPECIAL_TAG_ASSISTANT;
						}

						if (!tagMap.has(tagName)) {
						// Armazenar model.id para construir URL da API depois
						const modelId = item.model?.id || '';
						console.log('🔍 [TAGMAP] Tag:', tagName, '| Model ID:', modelId, '| item.model:', item.model);
						tagMap.set(tagName, {
							tag: tagName,
							models: [],
							icon: modelId
							});
						}
						tagMap.get(tagName)!.models.push(item);
					});
				} else {
					// Modelos sem tag vão para "Outros"
					if (!tagMap.has(SPECIAL_TAG_OTHER)) {
						tagMap.set(SPECIAL_TAG_OTHER, {
							tag: SPECIAL_TAG_OTHER,
							models: [],
							icon: ''
						});
					}
					tagMap.get(SPECIAL_TAG_OTHER)!.models.push(item);
				}
			});

		tagGroups = Array.from(tagMap.values()).sort((a, b) => {
			// "outros" sempre por último
			if (a.tag === SPECIAL_TAG_OTHER) return 1;
			if (b.tag === SPECIAL_TAG_OTHER) return -1;

			// "assistant" sempre penúltimo (antes de "outros")
			if (a.tag === SPECIAL_TAG_ASSISTANT) return 1;
			if (b.tag === SPECIAL_TAG_ASSISTANT) return -1;

			// Extrair prefixos numéricos para ordenação
			const aMatch = a.tag.match(/^(\d+)-/);
			const bMatch = b.tag.match(/^(\d+)-/);

			// Se ambas têm prefixo numérico, ordenar numericamente
			if (aMatch && bMatch) {
				const aNum = parseInt(aMatch[1], 10);
				const bNum = parseInt(bMatch[1], 10);
				return aNum - bNum;
			}

			// Se apenas uma tem prefixo, a com prefixo vem primeiro
			if (aMatch && !bMatch) return -1;
			if (!aMatch && bMatch) return 1;

			// Se nenhuma tem prefixo, ordem alfabética
			return a.tag.localeCompare(b.tag);
		});
	}

	// Função para remover o prefixo numérico das tags (ex: "1-chatgpt" -> "chatgpt")
	// E traduzir tags especiais
	const getDisplayTag = (tag: string): string => {
		// Traduzir tags especiais
		if (tag === SPECIAL_TAG_OTHER) {
			return $i18n.t('Other');
		}
		if (tag === SPECIAL_TAG_ASSISTANT) {
			return $i18n.t('Assistant');
		}

		// Remover prefixo numérico das tags normais (aceita múltiplos dígitos: 1-, 10-, 999-)
		return tag.replace(/^\d+-/, '');
	};

	// Fuse search para modelos
	let fuse: Fuse<any> | null = null;

	$: if (items) {
		fuse = new Fuse(
			items
				.filter((item) => !(item.model?.info?.meta?.hidden ?? false))
				.map((item) => {
					const _item = {
						...item,
						modelName: item.model?.name,
						tags: (item.model?.tags ?? []).map((tag: any) => tag.name).join(' '),
						desc: item.model?.info?.meta?.description
					};
					return _item;
				}),
			{
				keys: ['value', 'tags', 'modelName'],
				threshold: 0.4
			}
		);
	}

	// Modelos filtrados pela pesquisa
	let searchResults: typeof items = [];
	$: searchResults =
		searchValue && fuse
			? fuse.search(searchValue).map((e) => e.item)
			: items.filter((item) => !(item.model?.info?.meta?.hidden ?? false));

	// Grupos de tags filtrados pela pesquisa
	let filteredTagGroups: TagGroup[] = [];
	$: {
		if (searchValue) {
			// Quando há pesquisa, reagrupar apenas os resultados da pesquisa
			const tagMap = new Map<string, TagGroup>();

			searchResults.forEach((item) => {
				const modelTags = item.model?.tags ?? [];

				if (modelTags.length > 0) {
					modelTags.forEach((tag: any) => {
						let tagName = tag.name;

						// Detectar tag especial "assistant" e converter para valor interno
						if (tagName.toLowerCase() === 'assistant') {
							tagName = SPECIAL_TAG_ASSISTANT;
						}

						if (!tagMap.has(tagName)) {
						const modelId = item.model?.id || '';
						tagMap.set(tagName, {
							tag: tagName,
							models: [],
							icon: modelId
							});
						}
						tagMap.get(tagName)!.models.push(item);
					});
				} else {
					if (!tagMap.has(SPECIAL_TAG_OTHER)) {
						tagMap.set(SPECIAL_TAG_OTHER, {
							tag: SPECIAL_TAG_OTHER,
							models: [],
							icon: ''
						});
					}
					tagMap.get(SPECIAL_TAG_OTHER)!.models.push(item);
				}
			});

			filteredTagGroups = Array.from(tagMap.values())
				.filter((g) => g.models.length > 0)
				.sort((a, b) => {
					// "outros" sempre por último
					if (a.tag === SPECIAL_TAG_OTHER) return 1;
					if (b.tag === SPECIAL_TAG_OTHER) return -1;

					// "assistant" sempre penúltimo (antes de "outros")
					if (a.tag === SPECIAL_TAG_ASSISTANT) return 1;
					if (b.tag === SPECIAL_TAG_ASSISTANT) return -1;

					// Demais tags: prefixos numéricos ordenados numericamente (1-9, 10-99, etc)
					const aMatch = a.tag.match(/^(\d+)-/);
					const bMatch = b.tag.match(/^(\d+)-/);

					if (aMatch && bMatch) {
						const aNum = parseInt(aMatch[1], 10);
						const bNum = parseInt(bMatch[1], 10);
						return aNum - bNum;
					}

					// Tag com prefixo vem antes de tag sem prefixo
					if (aMatch && !bMatch) return -1;
					if (!aMatch && bMatch) return 1;

					// Ambas sem prefixo: ordem alfabética
					return a.tag.localeCompare(b.tag);
				});
		} else {
			// Sem pesquisa, usar todos os grupos
			filteredTagGroups = tagGroups;
		}
	}

	// Modelos a exibir na coluna direita
	$: filteredModels = selectedTag
		? (filteredTagGroups.find((g) => g.tag === selectedTag)?.models ?? [])
		: searchValue
			? searchResults
			: [];

	const resetView = async () => {
		await tick();

		if (selectedTag || searchValue) {
			const selectedInFiltered = filteredModels.findIndex((item: any) => item.value === value);

			if (selectedInFiltered >= 0) {
				selectedModelIdx = selectedInFiltered;
			} else {
				selectedModelIdx = 0;
			}

			await tick();
			const item = document.querySelector(`[data-arrow-selected="true"]`);
			item?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
		}
	};

	const selectTag = async (tag: string) => {
		selectedTag = tag;
		await resetView();
	};

	const pullModelHandler = async () => {
		const sanitizedModelTag = searchValue.trim().replace(/^ollama\s+(run|pull)\s+/, '');

		console.log($MODEL_DOWNLOAD_POOL);
		if ($MODEL_DOWNLOAD_POOL[sanitizedModelTag]) {
			toast.error(
				$i18n.t(`Model '{{modelTag}}' is already in queue for downloading.`, {
					modelTag: sanitizedModelTag
				})
			);
			return;
		}
		if (Object.keys($MODEL_DOWNLOAD_POOL).length === 3) {
			toast.error(
				$i18n.t('Maximum of 3 models can be downloaded simultaneously. Please try again later.')
			);
			return;
		}

		const [res, controller] = await pullModel(localStorage.token, sanitizedModelTag, 0).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);

		if (res) {
			const reader = res.body
				.pipeThrough(new TextDecoderStream())
				.pipeThrough(splitStream('\n'))
				.getReader();

			MODEL_DOWNLOAD_POOL.set({
				...$MODEL_DOWNLOAD_POOL,
				[sanitizedModelTag]: {
					...$MODEL_DOWNLOAD_POOL[sanitizedModelTag],
					abortController: controller,
					reader,
					done: false
				}
			});

			while (true) {
				try {
					const { value, done } = await reader.read();
					if (done) break;

					let lines = value.split('\n');

					for (const line of lines) {
						if (line !== '') {
							let data = JSON.parse(line);
							console.log(data);
							if (data.error) {
								throw data.error;
							}
							if (data.detail) {
								throw data.detail;
							}

							if (data.status) {
								if (data.digest) {
									let downloadProgress = 0;
									if (data.completed) {
										downloadProgress = Math.round((data.completed / data.total) * 1000) / 10;
									} else {
										downloadProgress = 100;
									}

									MODEL_DOWNLOAD_POOL.set({
										...$MODEL_DOWNLOAD_POOL,
										[sanitizedModelTag]: {
											...$MODEL_DOWNLOAD_POOL[sanitizedModelTag],
											pullProgress: downloadProgress,
											digest: data.digest
										}
									});
								} else {
									toast.success(data.status);

									MODEL_DOWNLOAD_POOL.set({
										...$MODEL_DOWNLOAD_POOL,
										[sanitizedModelTag]: {
											...$MODEL_DOWNLOAD_POOL[sanitizedModelTag],
											done: data.status === 'success'
										}
									});
								}
							}
						}
					}
				} catch (error) {
					console.log(error);
					if (typeof error !== 'string') {
						error = (error as any).message;
					}

					toast.error(`${error}`);
					break;
				}
			}

			if ($MODEL_DOWNLOAD_POOL[sanitizedModelTag].done) {
				toast.success(
					$i18n.t(`Model '{{modelName}}' has been successfully downloaded.`, {
						modelName: sanitizedModelTag
					})
				);

				models.set(
					await getModels(
						localStorage.token,
						$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
					)
				);
			} else {
				toast.error($i18n.t('Download canceled'));
			}

			delete $MODEL_DOWNLOAD_POOL[sanitizedModelTag];

			MODEL_DOWNLOAD_POOL.set({
				...$MODEL_DOWNLOAD_POOL
			});
		}
	};

	const setOllamaVersion = async () => {
		ollamaVersion = await getOllamaVersion(localStorage.token).catch((error) => false);
	};

	$: if (show) {
		setOllamaVersion();
	}

	const cancelModelPullHandler = async (model: string) => {
		const { reader, abortController } = $MODEL_DOWNLOAD_POOL[model];
		if (abortController) {
			abortController.abort();
		}
		if (reader) {
			await reader.cancel();
			delete $MODEL_DOWNLOAD_POOL[model];
			MODEL_DOWNLOAD_POOL.set({
				...$MODEL_DOWNLOAD_POOL
			});
			await deleteModel(localStorage.token, model);
			toast.success($i18n.t('{{model}} download has been canceled', { model: model }));
		}
	};

	const unloadModelHandler = async (model: string) => {
		const res = await unloadModel(localStorage.token, model).catch((error) => {
			toast.error($i18n.t('Error unloading model: {{error}}', { error }));
		});

		if (res) {
			toast.success($i18n.t('Model unloaded successfully'));
			models.set(
				await getModels(
					localStorage.token,
					$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
				)
			);
		}
	};
</script>

<DropdownMenu.Root
	bind:open={show}
	onOpenChange={async () => {
		searchValue = '';
		selectedTag = null;
		window.setTimeout(() => document.getElementById('model-search-input')?.focus(), 0);
	}}
	closeFocus={false}
>
	<DropdownMenu.Trigger
		class="relative w-full {($settings?.highContrastMode ?? false)
			? ''
			: 'outline-hidden focus:outline-hidden'}"
		aria-label={placeholder}
		id="model-selector-{id}-button"
	>
		<div
			class="flex w-full text-left px-0.5 bg-transparent truncate {triggerClassName} justify-between {($settings?.highContrastMode ??
			false)
				? 'dark:placeholder-gray-100 placeholder-gray-800'
				: 'placeholder-gray-400'}"
			on:mouseenter={async () => {
				models.set(
					await getModels(
						localStorage.token,
						$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
					)
				);
			}}
		>
			{#if selectedModel}
				{selectedModel.label}
			{:else}
				{placeholder}
			{/if}
			<ChevronDown className=" self-center ml-2 size-3" strokeWidth="2.5" />
		</div>
	</DropdownMenu.Trigger>

	<DropdownMenu.Content
		class=" z-40 {$mobile
			? `w-full`
			: `${className}`} max-w-[calc(100vw-1rem)] justify-start rounded-2xl  bg-white dark:bg-gray-850 dark:text-white shadow-lg  outline-hidden"
		transition={flyAndScale}
		side="bottom"
		align="start"
		sideOffset={2}
		alignOffset={-1}
	>
		<slot>
			{#if searchEnabled}
				<div class="flex items-center gap-2.5 px-4.5 mt-3.5 mb-1.5">
					<Search className="size-4" strokeWidth="2.5" />

					<input
						id="model-search-input"
						bind:value={searchValue}
						class="w-full text-sm bg-transparent outline-hidden"
						placeholder={searchPlaceholder}
						autocomplete="off"
						aria-label={$i18n.t('Search In Models')}
						on:keydown={(e) => {
							if (e.code === 'Enter' && filteredModels.length > 0) {
								value = filteredModels[selectedModelIdx].value;
								show = false;
								return;
							} else if (e.code === 'ArrowDown') {
								e.stopPropagation();
								selectedModelIdx = Math.min(selectedModelIdx + 1, filteredModels.length - 1);
							} else if (e.code === 'ArrowUp') {
								e.stopPropagation();
								selectedModelIdx = Math.max(selectedModelIdx - 1, 0);
							} else {
								selectedModelIdx = 0;
							}

							const item = document.querySelector(`[data-arrow-selected="true"]`);
							item?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
						}}
					/>
				</div>
			{/if}

		{#if searchValue}
			<!-- Modo de busca integrado com 2 colunas -->
			<div class="flex max-h-[calc(100vh-200px)]">
				<!-- Coluna da esquerda: Lista de Tags com contadores atualizados -->
				<div class="w-48 border-r border-gray-200 dark:border-gray-700 overflow-y-auto">
						{#each filteredTagGroups as group}
							<button
								class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors {selectedTag ===
								group.tag
									? 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white'
									: 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800/50'}"
								on:click={() => selectTag(group.tag)}
							>
								{#if group.icon}
									<img
									src={`/api/v1/models/model/profile/image?id=${group.icon}&lang=${$i18n.language}`}
										alt={getDisplayTag(group.tag)}
										class="size-5 rounded-sm flex-shrink-0"									on:load={() => console.log('✅ [IMG LOAD SEARCH] Tag:', getDisplayTag(group.tag), '| URL:', `/api/v1/models/model/profile/image?id=${group.icon}&lang=${$i18n.language}`)}
									on:error={(e) => console.log('❌ [IMG ERROR SEARCH] Tag:', getDisplayTag(group.tag), '| URL:', `/api/v1/models/model/profile/image?id=${group.icon}&lang=${$i18n.language}`, '| Error:', e)}									/>
								{:else if group.tag === SPECIAL_TAG_ASSISTANT}
									<svg
										class="size-5 flex-shrink-0 text-gray-400"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
										xmlns="http://www.w3.org/2000/svg"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
										/>
									</svg>
								{:else if group.tag === SPECIAL_TAG_OTHER}
									<svg
										class="size-5 flex-shrink-0 text-gray-400"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
										xmlns="http://www.w3.org/2000/svg"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
										/>
									</svg>
								{:else}
									<div class="size-5 flex-shrink-0"></div>
								{/if}
								<div class="flex-1 truncate capitalize">
									{getDisplayTag(group.tag)}
								</div>
								<div class="text-xs text-gray-500 dark:text-gray-400 flex-shrink-0">
									{group.models.length}
								</div>
							</button>
						{:else}
							<div class="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
								{$i18n.t('No results found')}
							</div>
						{/each}
					</div>

					<!-- Coluna da direita: Lista de Modelos filtrados -->
					<div class="flex-1 overflow-y-auto px-2.5">
						{#if selectedTag}
							{#each filteredModels as item, index}
								<ModelItem
									{selectedModelIdx}
									{item}
									{index}
									{value}
									{pinModelHandler}
									{unloadModelHandler}
									onClick={() => {
										value = item.value;
										selectedModelIdx = index;
										show = false;
									}}
								/>
							{:else}
								<div class="block px-3 py-2 text-sm text-gray-700 dark:text-gray-100">
									{$i18n.t('No models found')}
								</div>
							{/each}
						{:else}
							<!-- Quando não há tag selecionada, mostra todos os resultados da pesquisa -->
							{#each filteredModels as item, index}
								<ModelItem
									{selectedModelIdx}
									{item}
									{index}
									{value}
									{pinModelHandler}
									{unloadModelHandler}
									onClick={() => {
										value = item.value;
										selectedModelIdx = index;
										show = false;
									}}
								/>
							{:else}
								<div
									class="flex items-center justify-center h-full px-3 py-8 text-sm text-gray-500 dark:text-gray-400 text-center"
								>
									{$i18n.t('No results found')}
								</div>
							{/each}
						{/if}
					</div>
				</div>

				{#if !(searchValue.trim() in $MODEL_DOWNLOAD_POOL) && searchValue && ollamaVersion && $user?.role === 'admin'}
					<Tooltip
						content={$i18n.t(`Pull "{{searchValue}}" from Ollama.com`, {
							searchValue: searchValue
						})}
						placement="top-start"
					>
						<button
							class="flex w-full font-medium line-clamp-1 select-none items-center rounded-button py-2 pl-3 pr-1.5 text-sm text-gray-700 dark:text-gray-100 outline-hidden transition-all duration-75 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-xl cursor-pointer data-highlighted:bg-muted"
							on:click={() => {
								pullModelHandler();
							}}
						>
							<div class=" truncate">
								{$i18n.t(`Pull "{{searchValue}}" from Ollama.com`, { searchValue: searchValue })}
							</div>
						</button>
					</Tooltip>
				{/if}
		{:else}
			<!-- Layout de 2 colunas: Tags | Modelos -->
			<div class="flex max-h-[calc(100vh-200px)]">
				<!-- Coluna da esquerda: Lista de Tags -->
				<div class="w-48 border-r border-gray-200 dark:border-gray-700 overflow-y-auto">
						{#each filteredTagGroups as group}
							<button
								class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors {selectedTag ===
								group.tag
									? 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white'
									: 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800/50'}"
								on:click={() => selectTag(group.tag)}
							>
								{#if group.icon}
									<img
									src={`/api/v1/models/model/profile/image?id=${group.icon}&lang=${$i18n.language}`}
										alt={getDisplayTag(group.tag)}
										class="size-5 rounded-sm flex-shrink-0"									on:load={() => console.log('✅ [IMG LOAD] Tag:', getDisplayTag(group.tag), '| URL:', `/api/v1/models/model/profile/image?id=${group.icon}&lang=${$i18n.language}`)}
									on:error={(e) => console.log('❌ [IMG ERROR] Tag:', getDisplayTag(group.tag), '| URL:', `/api/v1/models/model/profile/image?id=${group.icon}&lang=${$i18n.language}`, '| Error:', e)}									/>
								{:else if group.tag === SPECIAL_TAG_ASSISTANT}
									<svg
										class="size-5 flex-shrink-0 text-gray-400"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
										xmlns="http://www.w3.org/2000/svg"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
										/>
									</svg>
								{:else if group.tag === SPECIAL_TAG_OTHER}
									<svg
										class="size-5 flex-shrink-0 text-gray-400"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
										xmlns="http://www.w3.org/2000/svg"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
										/>
									</svg>
								{:else}
									<div class="size-5 flex-shrink-0"></div>
								{/if}
								<div class="flex-1 truncate capitalize">
									{getDisplayTag(group.tag)}
								</div>
								<div class="text-xs text-gray-500 dark:text-gray-400 flex-shrink-0">
									{group.models.length}
								</div>
							</button>
						{/each}
					</div>

					<!-- Coluna da direita: Lista de Modelos -->
					<div class="flex-1 overflow-y-auto px-2.5">
						{#if selectedTag}
							{#each filteredModels as item, index}
								<ModelItem
									{selectedModelIdx}
									{item}
									{index}
									{value}
									{pinModelHandler}
									{unloadModelHandler}
									onClick={() => {
										value = item.value;
										selectedModelIdx = index;
										show = false;
									}}
								/>
							{:else}
								<div class="block px-3 py-2 text-sm text-gray-700 dark:text-gray-100">
									{$i18n.t('No models found')}
								</div>
							{/each}
						{:else}
							<div
								class="flex items-center justify-center h-full px-3 py-8 text-sm text-gray-500 dark:text-gray-400 text-center"
							>
								{$i18n.t('Select a model')}
							</div>
						{/if}
					</div>
				</div>
			{/if}

			{#each Object.keys($MODEL_DOWNLOAD_POOL) as model}
				<div
					class="flex w-full justify-between font-medium select-none rounded-button py-2 pl-3 pr-1.5 text-sm text-gray-700 dark:text-gray-100 outline-hidden transition-all duration-75 rounded-xl cursor-pointer data-highlighted:bg-muted"
				>
					<div class="flex">
						<div class="mr-2.5 translate-y-0.5">
							<Spinner />
						</div>

						<div class="flex flex-col self-start">
							<div class="flex gap-1">
								<div class="line-clamp-1">
									Downloading "{model}"
								</div>

								<div class="shrink-0">
									{'pullProgress' in $MODEL_DOWNLOAD_POOL[model]
										? `(${$MODEL_DOWNLOAD_POOL[model].pullProgress}%)`
										: ''}
								</div>
							</div>

							{#if 'digest' in $MODEL_DOWNLOAD_POOL[model] && $MODEL_DOWNLOAD_POOL[model].digest}
								<div class="-mt-1 h-fit text-[0.7rem] dark:text-gray-500 line-clamp-1">
									{$MODEL_DOWNLOAD_POOL[model].digest}
								</div>
							{/if}
						</div>
					</div>

					<div class="mr-2 ml-1 translate-y-0.5">
						<Tooltip content={$i18n.t('Cancel')}>
							<button
								class="text-gray-800 dark:text-gray-100"
								on:click={() => {
									cancelModelPullHandler(model);
								}}
							>
								<svg
									class="w-4 h-4 text-gray-800 dark:text-white"
									aria-hidden="true"
									xmlns="http://www.w3.org/2000/svg"
									width="24"
									height="24"
									fill="currentColor"
									viewBox="0 0 24 24"
								>
									<path
										stroke="currentColor"
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M6 18 17.94 6M18 18 6.06 6"
									/>
								</svg>
							</button>
						</Tooltip>
					</div>
				</div>
			{/each}

			<div class="mb-2.5"></div>
			<div class="hidden w-[42rem]" />
			<div class="hidden w-[32rem]" />
		</slot>
	</DropdownMenu.Content>
</DropdownMenu.Root>

<style>
	/* Ocultar os ícones de tag, external link e info do ModelItem */
	:global(.shrink-0.flex.items-center.gap-2) {
		display: none !important;
	}
</style>
