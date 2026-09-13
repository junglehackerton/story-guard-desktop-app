import { afterEach, expect, it, vi } from 'vitest';
import { api } from './api';

afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});

it('recovers a transient settings read without restarting the app', async()=>{
 vi.useFakeTimers();
 const fetcher=vi.fn().mockRejectedValueOnce(new TypeError('Load failed')).mockResolvedValueOnce(new Response('{"embedding_model":"qwen"}'));
 vi.stubGlobal('fetch',fetcher);
 const result=expect(api.settings()).resolves.toMatchObject({embedding_model:'qwen'});
 await vi.runAllTimersAsync();await result;
 expect(fetcher).toHaveBeenCalledTimes(2);
});

it('bounds repeated connection failures and identifies the failed request', async()=>{
 vi.useFakeTimers();const fetcher=vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));vi.stubGlobal('fetch',fetcher);
 const result=expect(api.listProjects()).rejects.toMatchObject({path:'/projects',method:'GET',attempts:3,kind:'network'});
 await vi.runAllTimersAsync();await result;expect(fetcher).toHaveBeenCalledTimes(3);
});

it('aborts stalled reads rather than leaving startup pending forever',async()=>{
 vi.useFakeTimers();const signals:AbortSignal[]=[];
 vi.stubGlobal('fetch',vi.fn((_url,options)=>new Promise((_resolve,reject)=>{signals.push(options.signal);options.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')));}))); 
 const result=expect(api.settings()).rejects.toMatchObject({kind:'timeout',attempts:3,path:'/settings'});
 await vi.advanceTimersByTimeAsync(32000);await result;
 expect(signals).toHaveLength(3);expect(signals.every(signal=>signal.aborted)).toBe(true);
});

it('does not retry GPT analysis after an ambiguous network failure',async()=>{
 const fetcher=vi.fn().mockRejectedValue(new TypeError('Load failed'));vi.stubGlobal('fetch',fetcher);
 await expect(api.analyzeProjectGpt(19,'luna','medium')).rejects.toThrow();expect(fetcher).toHaveBeenCalledTimes(1);
});

it('does not retry authentication failures',async()=>{
 const fetcher=vi.fn(async()=>new Response('{"detail":"인증 토큰이 필요합니다"}',{status:401}));vi.stubGlobal('fetch',fetcher);
 await expect(api.settings()).rejects.toMatchObject({status:401,attempts:1,kind:'http'});expect(fetcher).toHaveBeenCalledTimes(1);
});

it('distinguishes malformed JSON from a connection failure without retrying it',async()=>{
 const fetcher=vi.fn(async()=>new Response('not-json'));vi.stubGlobal('fetch',fetcher);
 await expect(api.settings()).rejects.toMatchObject({kind:'invalid_response',attempts:1});expect(fetcher).toHaveBeenCalledTimes(1);
});
