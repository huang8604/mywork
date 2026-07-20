<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import type { Word, WordPayload } from '@/types/domain'

const props = defineProps<{ modelValue: boolean; word?: Word | null; submitting?: boolean; error?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value:boolean]; submit: [payload:WordPayload] }>()
const formRef = ref<FormInstance>()
const form = reactive({ en_word:'', phonetic:'', cn_meaning:'', example_sentence:'', is_custom:false, tags:'' })
const rules: FormRules = {
  en_word:[{required:true,message:'请输入英文单词',trigger:'blur'},{pattern:/^[A-Za-z][A-Za-z '\-]*$/,message:'仅支持字母、空格、撇号和连字符',trigger:'blur'}],
  cn_meaning:[{required:true,message:'请输入中文释义',trigger:'blur'}],
}
watch(() => [props.modelValue, props.word] as const, () => {
  if (!props.modelValue) return; const word=props.word
  Object.assign(form,{en_word:word?.en_word??'',phonetic:word?.phonetic??'',cn_meaning:word?.cn_meaning??'',example_sentence:word?.example_sentence??'',is_custom:word?.is_custom??false,tags:word?.tags.join(', ')??''})
})
async function submit(){if(!await formRef.value?.validate().catch(()=>false))return;emit('submit',{en_word:form.en_word,phonetic:form.phonetic.trim()||null,cn_meaning:form.cn_meaning,example_sentence:form.example_sentence.trim()||null,is_custom:form.is_custom,tags:form.tags.split(/[,，]/).map(v=>v.trim()).filter(Boolean)})}
</script>
<template>
  <el-dialog :model-value="modelValue" :title="word?'编辑单词':'新增单词'" width="min(620px, calc(100vw - 24px))" destroy-on-close @update:model-value="emit('update:modelValue',$event)">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
      <div class="form-grid"><el-form-item label="英文" prop="en_word"><el-input v-model="form.en_word" maxlength="200" autofocus /></el-form-item><el-form-item label="音标"><el-input v-model="form.phonetic" maxlength="200" /></el-form-item></div>
      <el-form-item label="中文释义" prop="cn_meaning"><el-input v-model="form.cn_meaning" type="textarea" :rows="3" maxlength="2000" show-word-limit /></el-form-item>
      <el-form-item label="例句"><el-input v-model="form.example_sentence" type="textarea" :rows="3" maxlength="5000" /></el-form-item>
      <el-form-item label="标签（逗号分隔）"><el-input v-model="form.tags" placeholder="例如：四级, 工作" /></el-form-item>
      <el-form-item><el-checkbox v-model="form.is_custom">标记为自定义词</el-checkbox></el-form-item>
      <div v-if="error" class="error-box" role="alert">{{ error }}</div>
    </el-form>
    <template #footer><el-button @click="emit('update:modelValue',false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存</el-button></template>
  </el-dialog>
</template>
<style scoped>.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:639px){.form-grid{grid-template-columns:1fr}:global(.el-dialog){margin:0!important;width:100%!important;max-width:none;height:100%;border-radius:0}:global(.el-dialog__body){max-height:calc(100vh - 140px);overflow:auto}}</style>
