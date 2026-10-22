class AltheaRecorder extends AudioWorkletProcessor {
  process(inputs) {
    const samples=inputs[0]?.[0];
    if(samples?.length)this.port.postMessage(new Float32Array(samples));
    return true;
  }
}
registerProcessor('althea-recorder',AltheaRecorder);
